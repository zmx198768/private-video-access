import json
import tempfile
import time
import re
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.middleware.csrf import _get_new_csrf_string
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .ip_access import is_ip_blocked
from .models import (
    AccessCode,
    AdminAuditLog,
    PlaybackSession,
    SecurityEvent,
    SystemSettings,
    Video,
    ViewEvent,
    digest_access_code,
)
from .tasks import scan_video_directory
from .views import _stream_signature


class AccessCodeTests(TestCase):
    def setUp(self):
        self.video = Video.objects.create(
            title="测试视频",
            source_key="test-video",
            source_path="/video/test.mp4",
            processing_status=Video.ProcessingStatus.READY,
            hls_relative_path="video-id/index.m3u8",
            sharing_enabled=True,
        )

    def test_issue_creates_ten_character_unique_code_and_only_stores_digest(self):
        first, first_plain = AccessCode.issue(
            video=self.video, expires_at=timezone.now() + timezone.timedelta(days=1)
        )
        second, second_plain = AccessCode.issue(
            video=self.video, expires_at=timezone.now() + timezone.timedelta(days=1)
        )
        self.assertEqual(len(first_plain), 10)
        self.assertEqual(len(second_plain), 10)
        self.assertNotEqual(first_plain, second_plain)
        self.assertEqual(first.code_digest, digest_access_code(first_plain))
        self.assertNotIn(first_plain, first.code_digest)

    def test_video_share_state_requires_active_code(self):
        self.assertFalse(self.video.is_currently_shared)
        AccessCode.issue(video=self.video, expires_at=timezone.now() + timezone.timedelta(hours=1))
        self.assertTrue(self.video.is_currently_shared)
        self.video.sharing_enabled = False
        self.assertFalse(self.video.is_currently_shared)

    def test_video_code_cannot_duplicate_chat_room_code(self):
        from chat.models import ChatRoom

        ChatRoom.create_with_code(name="全局唯一性", code="GLOBAL2626")
        with self.assertRaisesMessage(ValueError, "授权码已被其他内容使用"):
            AccessCode.issue_custom(
                code="GLOBAL2626",
                video=self.video,
                expires_at=timezone.now() + timezone.timedelta(days=1),
            )


class PlaybackFlowTests(TestCase):
    def setUp(self):
        self.hls_temp = tempfile.TemporaryDirectory()
        self.hls_root = Path(self.hls_temp.name)
        self.video = Video.objects.create(
            title="受保护视频",
            source_key="protected-video",
            source_path="/video/protected.mp4",
            processing_status=Video.ProcessingStatus.READY,
            hls_relative_path="placeholder",
            sharing_enabled=True,
        )
        video_dir = self.hls_root / str(self.video.id)
        video_dir.mkdir()
        (video_dir / "index.m3u8").write_text(
            "#EXTM3U\n#EXT-X-MAP:URI=\"init.mp4\"\n#EXTINF:6,\nseg_00000.m4s\n#EXT-X-ENDLIST\n",
            encoding="utf-8",
        )
        (video_dir / "init.mp4").write_bytes(b"init")
        (video_dir / "seg_00000.m4s").write_bytes(b"segment")
        self.video.hls_relative_path = f"{self.video.id}/index.m3u8"
        self.video.save()
        self.code, self.plain = AccessCode.issue(
            video=self.video, expires_at=timezone.now() + timezone.timedelta(hours=1)
        )

    def tearDown(self):
        self.hls_temp.cleanup()

    def test_valid_code_creates_session_and_invalid_code_is_audited(self):
        response = self.client.post(reverse("videos:authorize"), {"code": self.plain})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PlaybackSession.objects.count(), 1)
        self.assertEqual(ViewEvent.objects.filter(event_type="authorized").count(), 1)

        response = self.client.post(reverse("videos:authorize"), {"code": "AAAAAAAAAA"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(SecurityEvent.objects.filter(event_type="invalid_code").count(), 1)

    def test_public_entry_is_unified_and_hides_staff_navigation(self):
        user = get_user_model().objects.create_user(
            "entry-admin",
            password="strong-test-password",
            is_staff=True,
        )
        self.client.force_login(user)
        response = self.client.get(reverse("videos:access"))
        self.assertContains(response, "私密视频/聊天入口")
        self.assertContains(response, "视频或聊天室")
        self.assertNotContains(response, "系统主菜单")
        self.assertNotContains(response, 'class="system-name"')
        self.assertNotContains(response, "访问时间和IP地址会被记录")

    def test_watch_page_hides_staff_navigation_after_authorization(self):
        user = get_user_model().objects.create_user(
            "watching-admin",
            password="strong-test-password",
            is_staff=True,
        )
        session, token = PlaybackSession.create_for(
            self.code,
            "127.0.0.1",
            "staff-watch",
        )
        self.client.force_login(user)
        self.client.cookies[f"pv_{str(session.id).replace('-', '')}"] = token
        response = self.client.get(reverse("videos:watch", args=[session.id]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "系统主菜单")

    def test_fresh_csrf_endpoint_recovers_after_login_rotates_cookie(self):
        user = get_user_model().objects.create_user("csrf-admin", password="strong-test-password", is_staff=True)
        client = Client(enforce_csrf_checks=True)
        page = client.get(reverse("videos:access"))
        old_token = re.search(
            rb'name="csrfmiddlewaretoken" value="([^"]+)"', page.content
        ).group(1).decode()

        self.assertTrue(client.login(username=user.username, password="strong-test-password"))
        client.cookies[settings.CSRF_COOKIE_NAME] = _get_new_csrf_string()
        stale_response = client.post(
            reverse("videos:authorize"),
            {"code": self.plain, "csrfmiddlewaretoken": old_token},
        )
        self.assertEqual(stale_response.status_code, 403)

        fresh_token = client.get(reverse("videos:csrf_token")).json()["csrfToken"]
        recovered_response = client.post(
            reverse("videos:authorize"),
            {"code": self.plain, "csrfmiddlewaretoken": fresh_token},
        )
        self.assertEqual(recovered_response.status_code, 302)

    def test_expired_code_is_rejected(self):
        self.code.expires_at = timezone.now() - timezone.timedelta(seconds=1)
        self.code.save()
        response = self.client.post(reverse("videos:authorize"), {"code": self.plain})
        self.assertEqual(response.status_code, 403)

    def test_stopped_video_invalidates_existing_session(self):
        session, token = PlaybackSession.create_for(self.code, "127.0.0.1", "test")
        self.client.cookies[f"pv_{str(session.id).replace('-', '')}"] = token
        self.video.sharing_enabled = False
        self.video.save()
        response = self.client.get(reverse("videos:watch", args=[session.id]))
        self.assertEqual(response.status_code, 403)

    def test_signed_segment_rejects_tampering(self):
        session, _ = PlaybackSession.create_for(self.code, "127.0.0.1", "test")
        expires = str(int(time.time()) + 120)
        good = _stream_signature(session.id, "seg_00000.m4s", expires)
        url = reverse("videos:stream_asset", args=[session.id, "seg_00000.m4s"])
        with override_settings(VIDEO_HLS_DIR=self.hls_root):
            response = self.client.get(url, {"expires": expires, "sig": good})
            self.assertEqual(response.status_code, 200)
            self.assertIn("X-Accel-Redirect", response)
            response = self.client.get(url, {"expires": expires, "sig": "bad"})
            self.assertEqual(response.status_code, 403)

    def test_manifest_rewrites_segment_to_signed_route(self):
        session, token = PlaybackSession.create_for(self.code, "127.0.0.1", "test")
        self.client.cookies[f"pv_{str(session.id).replace('-', '')}"] = token
        with override_settings(VIDEO_HLS_DIR=self.hls_root):
            response = self.client.get(reverse("videos:manifest", args=[session.id]))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn(f"/stream/{session.id}/seg_00000.m4s", body)
        self.assertIn(f"/stream/{session.id}/init.mp4", body)
        self.assertIn("sig=", body)
        self.assertNotIn("\nseg_00000.m4s\n", body)


class ScannerTests(TestCase):
    def test_file_is_queued_only_after_two_stable_scans(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "demo.mp4"
            source.write_bytes(b"not-yet-a-real-video")
            with override_settings(VIDEO_SOURCE_DIR=Path(directory), VIDEO_STABLE_SCANS=2):
                scan_video_directory()
                video = Video.objects.get()
                self.assertEqual(video.processing_status, Video.ProcessingStatus.DISCOVERED)
                with self.settings(CELERY_TASK_ALWAYS_EAGER=False):
                    # Avoid dispatching a real worker during the unit test.
                    from unittest.mock import patch
                    with patch("videos.tasks.transcode_video.delay") as delay:
                        scan_video_directory()
                        video.refresh_from_db()
                        self.assertEqual(video.processing_status, Video.ProcessingStatus.QUEUED)
                        delay.assert_called_once_with(str(video.id))


class ManagementTests(TestCase):
    def test_primary_management_pages_do_not_render_legacy_hero_header(self):
        user = get_user_model().objects.create_user(
            "compact-admin",
            password="strong-test-password",
            is_staff=True,
        )
        self.client.force_login(user)
        for url_name in (
            "videos:manage",
            "videos:records",
            "videos:settings",
            "chat:manage",
        ):
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'class="admin-header"')

    def test_staff_can_create_multiple_codes_and_creation_enables_sharing(self):
        user = get_user_model().objects.create_user("admin", password="strong-test-password", is_staff=True)
        self.client.force_login(user)
        video = Video.objects.create(
            title="管理测试",
            source_key="manage-video",
            source_path="/video/manage.mp4",
            processing_status=Video.ProcessingStatus.READY,
            hls_relative_path="manage/index.m3u8",
        )
        response = self.client.post(
            reverse("videos:create_codes", args=[video.id]),
            {
                "starts_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
                "expires_at": (timezone.localtime() + timezone.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
                "code_mode": "auto",
                "quantity": 3,
                "note": "客户A",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(video.access_codes.count(), 3)
        video.refresh_from_db()
        self.assertTrue(video.sharing_enabled)

        response = self.client.post(reverse("videos:toggle_video", args=[video.id]))
        self.assertEqual(response.status_code, 302)
        video.refresh_from_db()
        self.assertFalse(video.sharing_enabled)

    def test_deleting_code_hides_it_revokes_sessions_and_rejects_authorization(self):
        user = get_user_model().objects.create_user("deleter", password="strong-test-password", is_staff=True)
        self.client.force_login(user)
        video = Video.objects.create(
            title="删除授权码测试",
            source_key="delete-code-video",
            source_path="/video/delete-code.mp4",
            processing_status=Video.ProcessingStatus.READY,
            hls_relative_path="delete-code/index.m3u8",
            sharing_enabled=True,
        )
        code, plain = AccessCode.issue(
            video=video,
            expires_at=timezone.now() + timezone.timedelta(days=1),
        )
        session, _ = PlaybackSession.create_for(code, "127.0.0.1", "test")

        response = self.client.post(reverse("videos:delete_code", args=[code.id]), follow=True)
        self.assertEqual(response.status_code, 200)
        code.refresh_from_db()
        session.refresh_from_db()
        self.assertIsNotNone(code.deleted_at)
        self.assertFalse(code.enabled)
        self.assertEqual(session.state, PlaybackSession.State.REVOKED)
        self.assertContains(response, "授权码 0 个")
        self.assertNotContains(response, reverse("videos:delete_code", args=[code.id]))

        self.client.logout()
        response = self.client.post(reverse("videos:authorize"), {"code": plain})
        self.assertEqual(response.status_code, 403)

    def test_code_creation_page_has_defaults_and_clear_layout(self):
        user = get_user_model().objects.create_user("designer", password="strong-test-password", is_staff=True)
        self.client.force_login(user)
        video = Video.objects.create(
            title="页面设计测试",
            source_key="design-video",
            source_path="/video/design.mp4",
            processing_status=Video.ProcessingStatus.READY,
            hls_relative_path="design/index.m3u8",
        )
        response = self.client.get(reverse("videos:create_codes", args=[video.id]))
        self.assertContains(response, "生成查看授权码")
        self.assertContains(response, 'value="1"')
        self.assertContains(response, 'type="datetime-local"', count=2)
        self.assertContains(response, "快速设置")
        self.assertContains(response, "手工设置")

    def test_staff_can_create_and_use_a_manual_code(self):
        user = get_user_model().objects.create_user("manual-admin", password="strong-test-password", is_staff=True)
        self.client.force_login(user)
        video = Video.objects.create(
            title="手工授权码测试",
            source_key="manual-code-video",
            source_path="/video/manual.mp4",
            processing_status=Video.ProcessingStatus.READY,
            hls_relative_path="manual/index.m3u8",
        )
        response = self.client.post(
            reverse("videos:create_codes", args=[video.id]),
            {
                "starts_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
                "expires_at": (timezone.localtime() + timezone.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
                "code_mode": "manual",
                "custom_code": "Abcd2efgh3",
                "quantity": 9,
                "note": "手工分配",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ABCD2EFGH3")
        self.assertEqual(video.access_codes.count(), 1)
        self.assertEqual(video.access_codes.get().code_digest, digest_access_code("ABCD2EFGH3"))

        self.client.logout()
        response = self.client.post(reverse("videos:authorize"), {"code": "abcd2efgh3"})
        self.assertEqual(response.status_code, 302)

    def test_manual_code_cannot_reuse_an_existing_or_deleted_code(self):
        user = get_user_model().objects.create_user("unique-admin", password="strong-test-password", is_staff=True)
        self.client.force_login(user)
        video = Video.objects.create(
            title="唯一授权码测试",
            source_key="unique-code-video",
            source_path="/video/unique.mp4",
            processing_status=Video.ProcessingStatus.READY,
            hls_relative_path="unique/index.m3u8",
        )
        AccessCode.issue_custom(
            code="CUSTOM2026",
            video=video,
            expires_at=timezone.now() + timezone.timedelta(days=1),
        )
        response = self.client.post(
            reverse("videos:create_codes", args=[video.id]),
            {
                "starts_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
                "expires_at": (timezone.localtime() + timezone.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
                "code_mode": "manual",
                "custom_code": "custom2026",
                "quantity": 1,
                "note": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "该授权码已被其他内容使用")
        self.assertEqual(video.access_codes.count(), 1)

    def test_view_records_are_paginated(self):
        user = get_user_model().objects.create_user("records-admin", password="strong-test-password", is_staff=True)
        self.client.force_login(user)
        video = Video.objects.create(
            title="分页测试",
            source_key="records-video",
            source_path="/video/records.mp4",
            processing_status=Video.ProcessingStatus.READY,
            hls_relative_path="records/index.m3u8",
            sharing_enabled=True,
        )
        code, _ = AccessCode.issue(
            video=video,
            expires_at=timezone.now() + timezone.timedelta(days=1),
        )
        for index in range(31):
            PlaybackSession.create_for(code, f"192.0.2.{index + 1}", "test")

        first_page = self.client.get(reverse("videos:records"))
        second_page = self.client.get(reverse("videos:records"), {"page": 2})
        self.assertEqual(len(first_page.context["page_obj"].object_list), 25)
        self.assertEqual(len(second_page.context["page_obj"].object_list), 6)
        self.assertContains(first_page, "共 31 条记录")
        self.assertContains(first_page, "?page=2")

    def test_staff_can_rename_video_without_changing_source_path(self):
        user = get_user_model().objects.create_user("rename-admin", password="strong-test-password", is_staff=True)
        self.client.force_login(user)
        video = Video.objects.create(
            title="a8f12638d9",
            source_key="rename-video",
            source_path="/video/a8f12638d9.mp4",
        )
        response = self.client.post(
            reverse("videos:rename_video", args=[video.id]),
            {"title": "产品发布会完整版"},
        )
        self.assertRedirects(response, reverse("videos:manage"))
        video.refresh_from_db()
        self.assertEqual(video.title, "产品发布会完整版")
        self.assertEqual(video.source_path, "/video/a8f12638d9.mp4")

    def test_mp4_upload_uses_random_filename_and_custom_title(self):
        user = get_user_model().objects.create_user("upload-admin", password="strong-test-password", is_staff=True)
        self.client.force_login(user)
        mp4_bytes = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isomiso2" + b"\x00" * 64
        probe_result = type(
            "ProbeResult",
            (),
            {
                "stdout": json.dumps(
                    {
                        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
                        "streams": [{"codec_type": "video", "codec_name": "h264"}],
                    }
                )
            },
        )()
        with tempfile.TemporaryDirectory() as directory, override_settings(
            VIDEO_SOURCE_DIR=Path(directory),
            MAX_VIDEO_UPLOAD_BYTES=1024 * 1024,
        ), patch("videos.views.subprocess.run", return_value=probe_result):
            upload = SimpleUploadedFile("meaningless-name.mp4", mp4_bytes, content_type="video/mp4")
            response = self.client.post(
                reverse("videos:upload_video"),
                {"title": "客户培训视频", "video_file": upload},
            )
            self.assertRedirects(response, reverse("videos:manage"))
            video = Video.objects.get(title="客户培训视频")
            saved_path = Path(video.source_path)
            self.assertEqual(saved_path.parent, Path(directory))
            self.assertEqual(saved_path.suffix, ".mp4")
            self.assertNotEqual(saved_path.name, "meaningless-name.mp4")
            self.assertTrue(saved_path.is_file())

    def test_upload_rejects_non_mp4_extension(self):
        user = get_user_model().objects.create_user("reject-upload-admin", password="strong-test-password", is_staff=True)
        self.client.force_login(user)
        with tempfile.TemporaryDirectory() as directory, override_settings(
            VIDEO_SOURCE_DIR=Path(directory),
            MAX_VIDEO_UPLOAD_BYTES=1024 * 1024,
        ):
            upload = SimpleUploadedFile(
                "wrong.mov",
                b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64,
                content_type="video/quicktime",
            )
            response = self.client.post(
                reverse("videos:upload_video"),
                {"title": "错误格式", "video_file": upload},
            )
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "仅允许上传 .mp4 格式")
            self.assertFalse(Video.objects.filter(title="错误格式").exists())
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_staff_can_update_system_name_without_exposing_it_on_public_entry(self):
        user = get_user_model().objects.create_user("settings-admin", password="strong-test-password", is_staff=True)
        self.client.force_login(user)
        response = self.client.post(
            reverse("videos:settings"),
            {
                "action": "system_name",
                "identity-system_name": "星河视频中心",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "系统名称已更新")
        self.assertEqual(SystemSettings.load().system_name, "星河视频中心")

        self.client.logout()
        response = self.client.get(reverse("videos:access"))
        self.assertNotContains(response, "星河视频中心")
        self.assertContains(response, "私密视频/聊天入口")

    def test_staff_can_update_ip_blacklist_with_regular_expressions(self):
        user = get_user_model().objects.create_user(
            "network-admin",
            password="strong-test-password",
            is_staff=True,
        )
        self.client.force_login(user)
        response = self.client.post(
            reverse("videos:settings"),
            {
                "action": "ip_blacklist",
                "network-ip_blacklist": (
                    r"^203\.0\.113\.25$" "\n"
                    r"^198\.51\.100\.\d{1,3}$"
                ),
            },
            REMOTE_ADDR="192.0.2.10",
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "IP黑名单已更新")
        self.assertEqual(
            SystemSettings.load().ip_blacklist,
            r"^203\.0\.113\.25$" "\n" r"^198\.51\.100\.\d{1,3}$",
        )
        self.assertTrue(
            AdminAuditLog.objects.filter(
                actor=user,
                action="update_ip_blacklist",
            ).exists()
        )

    def test_ip_blacklist_rejects_invalid_regular_expression(self):
        user = get_user_model().objects.create_user(
            "invalid-network-admin",
            password="strong-test-password",
            is_staff=True,
        )
        self.client.force_login(user)
        response = self.client.post(
            reverse("videos:settings"),
            {
                "action": "ip_blacklist",
                "network-ip_blacklist": "[invalid",
            },
            REMOTE_ADDR="192.0.2.11",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "规则无效")
        self.assertEqual(SystemSettings.load().ip_blacklist, "")

    def test_ip_blacklist_prevents_locking_current_admin_ip(self):
        user = get_user_model().objects.create_user(
            "lockout-admin",
            password="strong-test-password",
            is_staff=True,
        )
        self.client.force_login(user)
        response = self.client.post(
            reverse("videos:settings"),
            {
                "action": "ip_blacklist",
                "network-ip_blacklist": r"^192\.0\.2\.\d+$",
            },
            REMOTE_ADDR="192.0.2.12",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "规则会命中当前管理IP")
        self.assertEqual(SystemSettings.load().ip_blacklist, "")

    def test_non_staff_cannot_update_ip_blacklist(self):
        user = get_user_model().objects.create_user(
            "ordinary-user",
            password="strong-test-password",
        )
        self.client.force_login(user)
        response = self.client.post(
            reverse("videos:settings"),
            {
                "action": "ip_blacklist",
                "network-ip_blacklist": r"^203\.0\.113\.25$",
            },
            REMOTE_ADDR="192.0.2.13",
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])
        self.assertEqual(SystemSettings.load().ip_blacklist, "")

    def test_blacklisted_ip_is_denied_and_security_event_is_recorded(self):
        settings_obj = SystemSettings.load()
        settings_obj.ip_blacklist = r"^203\.0\.113\.\d{1,3}$"
        settings_obj.save()

        denied = self.client.get(
            reverse("videos:access"),
            REMOTE_ADDR="203.0.113.42",
            HTTP_USER_AGENT="Blacklist test",
        )
        self.assertEqual(denied.status_code, 403)
        self.assertContains(denied, "该IP已被禁止访问", status_code=403)
        self.assertTrue(
            SecurityEvent.objects.filter(
                event_type="ip_blacklisted",
                ip_address="203.0.113.42",
            ).exists()
        )

        allowed = self.client.get(
            reverse("videos:access"),
            REMOTE_ADDR="198.51.100.42",
        )
        self.assertEqual(allowed.status_code, 200)

    @override_settings(TRUST_PROXY_HEADERS=True)
    def test_ip_blacklist_uses_trusted_real_ip_header(self):
        settings_obj = SystemSettings.load()
        settings_obj.ip_blacklist = r"^203\.0\.113\.77$"
        settings_obj.save()

        response = self.client.get(
            reverse("videos:access"),
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_REAL_IP="203.0.113.77",
        )
        self.assertEqual(response.status_code, 403)

    def test_ip_blacklist_accepts_plain_ip_and_wildcard_without_escaping(self):
        user = get_user_model().objects.create_user(
            "friendly-blacklist-admin",
            password="strong-test-password",
            is_staff=True,
        )
        self.client.force_login(user)
        response = self.client.post(
            reverse("videos:settings"),
            {
                "action": "ip_blacklist",
                "network-ip_blacklist": "203.0.113.25\n198.51.100.*",
            },
            REMOTE_ADDR="192.0.2.10",
        )
        self.assertRedirects(response, reverse("videos:settings"))
        blacklist = SystemSettings.load().ip_blacklist
        self.assertTrue(is_ip_blocked("203.0.113.25", blacklist))
        self.assertTrue(is_ip_blocked("198.51.100.88", blacklist))
        self.assertFalse(is_ip_blocked("198.51.101.88", blacklist))

    def test_staff_can_change_password_without_losing_session(self):
        user = get_user_model().objects.create_user("password-admin", password="old-strong-password", is_staff=True)
        self.client.force_login(user)
        response = self.client.post(
            reverse("videos:settings"),
            {
                "action": "password",
                "password-old_password": "old-strong-password",
                "password-new_password1": "N7!river-Moon-Quartz-2026",
                "password-new_password2": "N7!river-Moon-Quartz-2026",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "管理员密码已修改")
        user.refresh_from_db()
        self.assertTrue(user.check_password("N7!river-Moon-Quartz-2026"))
        self.assertEqual(self.client.get(reverse("videos:settings")).status_code, 200)

    def test_django_admin_has_primary_system_menu(self):
        user = get_user_model().objects.create_superuser("super-admin", password="strong-test-password")
        self.client.force_login(user)
        response = self.client.get("/admin/")
        self.assertContains(response, "私密视频")
        self.assertContains(response, "私密聊天")
        self.assertContains(response, "系统设置")
        self.assertContains(response, "系统管理")

    def test_staff_pages_have_two_level_primary_navigation(self):
        user = get_user_model().objects.create_user(
            "menu-admin",
            password="strong-test-password",
            is_staff=True,
        )
        self.client.force_login(user)
        response = self.client.get(reverse("videos:manage"))
        self.assertContains(response, "系统主菜单")
        self.assertContains(response, "私密视频")
        self.assertContains(response, "私密聊天")
        self.assertContains(response, "系统设置")
        self.assertContains(response, "系统管理")
        self.assertContains(response, "视频共享控制台")
        self.assertContains(response, "聊天室管理")
        self.assertContains(response, "聊天参与记录")
        self.assertContains(response, 'class="system-nav-direct')
        self.assertNotContains(response, "<summary>系统设置</summary>", html=False)
        self.assertContains(response, 'name="system-menu"')
        self.assertContains(response, "js/admin-navigation.js")
        self.assertNotContains(response, 'class="admin-header"')

    def test_settings_page_uses_friendly_ip_rule_examples(self):
        user = get_user_model().objects.create_user(
            "settings-layout-admin",
            password="strong-test-password",
            is_staff=True,
        )
        self.client.force_login(user)
        response = self.client.get(reverse("videos:settings"))
        self.assertContains(response, "整个系统的名称")
        self.assertContains(response, "203.0.113.25")
        self.assertContains(response, "198.51.100.*")
        self.assertNotContains(response, r"^203\.0\.113\.25$")
        self.assertContains(response, reverse("videos:manage"))
        self.assertContains(response, "identity-name-field")

    def test_dashboard_displays_video_upload_time(self):
        user = get_user_model().objects.create_user("time-admin", password="strong-test-password", is_staff=True)
        self.client.force_login(user)
        video = Video.objects.create(
            title="上传时间测试",
            source_key="upload-time-video",
            source_path="/video/upload-time.mp4",
        )
        expected = timezone.localtime(video.discovered_at).strftime("%Y-%m-%d %H:%M:%S")
        response = self.client.get(reverse("videos:manage"))
        self.assertContains(response, "上传时间：")
        self.assertContains(response, expected)
