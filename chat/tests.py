import uuid

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from private_video.asgi import application
from videos.models import AdminAuditLog, SecurityEvent, SystemSettings, digest_access_code
from videos.models import AccessCode, Video

from .models import ChatMessage, ChatParticipant, ChatRoom
from .nicknames import NICKNAME_GROUPS


TEST_CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
}


class ChatRoomManagementTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            "chat-admin",
            password="strong-test-password",
            is_staff=True,
        )

    def test_management_requires_staff_login(self):
        response = self.client.get(reverse("chat:manage"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)

    def test_staff_can_create_room_with_random_code_and_plaintext_is_not_stored(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("chat:create"),
            {"name": "项目讨论", "code_mode": "auto", "custom_code": ""},
        )
        self.assertEqual(response.status_code, 200)
        room = ChatRoom.objects.get()
        self.assertEqual(len(room.code_digest), 64)
        self.assertNotContains(response, room.code_digest)
        self.assertContains(response, "这是唯一一次显示完整授权码")
        self.assertTrue(AdminAuditLog.objects.filter(action="create_chat_room").exists())

    def test_staff_can_create_room_with_manual_code(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("chat:create"),
            {"name": "手工授权聊天室", "code_mode": "manual", "custom_code": "chatroom26"},
        )
        self.assertEqual(response.status_code, 200)
        room = ChatRoom.objects.get()
        self.assertEqual(room.code_digest, digest_access_code("CHATROOM26"))
        self.assertContains(response, "CHATROOM26")

    def test_chat_code_cannot_duplicate_video_code(self):
        video = Video.objects.create(
            title="跨类型授权码",
            source_key="global-code-video",
            source_path="/video/global-code.mp4",
        )
        AccessCode.issue_custom(
            code="SHARED2626",
            video=video,
            expires_at=timezone.now() + timezone.timedelta(days=1),
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("chat:create"),
            {
                "name": "冲突聊天室",
                "code_mode": "manual",
                "custom_code": "SHARED2626",
                "nickname_group": "auto",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "授权码已被其他内容使用")
        self.assertFalse(ChatRoom.objects.exists())

    def test_chat_creation_page_matches_access_code_flow_and_offers_nickname_groups(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("chat:create"))
        self.assertContains(response, "聊天室信息")
        self.assertContains(response, "授权码设置")
        self.assertContains(response, "自动生成")
        self.assertContains(response, "手工设置")
        self.assertContains(response, "备用昵称组")
        self.assertContains(response, "系统随机选择")

    def test_non_staff_cannot_toggle_room(self):
        room, _ = ChatRoom.create_with_code(name="权限测试")
        user = get_user_model().objects.create_user("ordinary", password="strong-test-password")
        self.client.force_login(user)
        response = self.client.post(reverse("chat:toggle", args=[room.id]))
        self.assertEqual(response.status_code, 302)
        room.refresh_from_db()
        self.assertTrue(room.is_active)

    def test_room_management_is_paginated(self):
        self.client.force_login(self.user)
        for index in range(31):
            ChatRoom.create_with_code(name=f"分页聊天室 {index:02}")
        first_page = self.client.get(reverse("chat:manage"))
        second_page = self.client.get(reverse("chat:manage"), {"page": 2})
        self.assertEqual(len(first_page.context["page_obj"].object_list), 25)
        self.assertEqual(len(second_page.context["page_obj"].object_list), 6)
        self.assertContains(first_page, "聊天室总数")
        self.assertContains(first_page, "?page=2")

    def test_participant_records_are_staff_only_paginated_and_show_last_message(self):
        room, _ = ChatRoom.create_with_code(name="参与记录聊天室")
        recorded_participant = None
        for index in range(31):
            participant, _ = ChatParticipant.create_for(
                room=room,
                ip_address=f"192.0.2.{index + 1}",
                user_agent=f"participant-{index}",
            )
            recorded_participant = participant
        ChatMessage.objects.create(
            room=room,
            participant=recorded_participant,
            body="参与记录消息",
            client_nonce=uuid.uuid4(),
        )

        anonymous = self.client.get(reverse("chat:participants"))
        self.assertEqual(anonymous.status_code, 302)

        self.client.force_login(self.user)
        first_page = self.client.get(reverse("chat:participants"))
        second_page = self.client.get(reverse("chat:participants"), {"page": 2})
        self.assertEqual(len(first_page.context["page_obj"].object_list), 25)
        self.assertEqual(len(second_page.context["page_obj"].object_list), 6)
        self.assertContains(first_page, "聊天参与记录")
        self.assertContains(first_page, "最后发言时间")
        self.assertContains(first_page, "192.0.2.")
        recorded = next(
            item
            for item in first_page.context["page_obj"].object_list
            if item.pk == recorded_participant.pk
        )
        self.assertIsNotNone(recorded.last_spoke_at)

    def test_room_message_records_are_filtered_paginated_and_linked_from_management(self):
        room, _ = ChatRoom.create_with_code(name="消息记录聊天室")
        other_room, _ = ChatRoom.create_with_code(name="其他聊天室")
        participant, _ = ChatParticipant.create_for(
            room=room,
            ip_address="192.0.2.88",
            user_agent="message-records",
        )
        other_participant, _ = ChatParticipant.create_for(
            room=other_room,
            ip_address="192.0.2.89",
            user_agent="other-room",
        )
        ChatMessage.objects.bulk_create(
            [
                ChatMessage(
                    room=room,
                    participant=participant,
                    body=f"房间消息 {index:02}",
                    client_nonce=uuid.uuid4(),
                )
                for index in range(51)
            ]
            + [
                ChatMessage(
                    room=other_room,
                    participant=other_participant,
                    body="不应显示的其他房间消息",
                    client_nonce=uuid.uuid4(),
                )
            ]
        )

        records_url = reverse("chat:message_records", args=[room.id])
        anonymous = self.client.get(records_url)
        self.assertEqual(anonymous.status_code, 302)

        self.client.force_login(self.user)
        management = self.client.get(reverse("chat:manage"))
        self.assertContains(management, records_url)
        self.assertContains(management, "查看聊天记录")

        first_page = self.client.get(records_url)
        second_page = self.client.get(records_url, {"page": 2})
        self.assertEqual(len(first_page.context["page_obj"].object_list), 50)
        self.assertEqual(len(second_page.context["page_obj"].object_list), 1)
        self.assertContains(first_page, "消息记录聊天室")
        self.assertContains(first_page, "房间消息")
        self.assertNotContains(first_page, "不应显示的其他房间消息")

    def test_closing_room_revokes_existing_participants(self):
        self.client.force_login(self.user)
        room, _ = ChatRoom.create_with_code(name="关闭测试")
        participant, _ = ChatParticipant.create_for(
            room=room,
            ip_address="127.0.0.1",
            user_agent="test",
        )
        response = self.client.post(reverse("chat:toggle", args=[room.id]))
        self.assertRedirects(response, reverse("chat:manage"))
        room.refresh_from_db()
        participant.refresh_from_db()
        self.assertFalse(room.is_active)
        self.assertIsNotNone(participant.revoked_at)

    def test_rotating_code_revokes_old_sessions_and_invalidates_old_code(self):
        self.client.force_login(self.user)
        room, old_code = ChatRoom.create_with_code(name="轮换测试", code="OLDCODE226")
        participant, _ = ChatParticipant.create_for(
            room=room,
            ip_address="127.0.0.1",
            user_agent="test",
        )
        response = self.client.post(
            reverse("chat:rotate_code", args=[room.id]),
            {"code_mode": "manual", "custom_code": "NEWCODE226"},
        )
        self.assertEqual(response.status_code, 200)
        room.refresh_from_db()
        participant.refresh_from_db()
        self.assertEqual(room.code_digest, digest_access_code("NEWCODE226"))
        self.assertNotEqual(room.code_digest, digest_access_code(old_code))
        self.assertIsNotNone(participant.revoked_at)


class ChatEntryAndHistoryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.room, self.plain = ChatRoom.create_with_code(
            name="公开测试聊天室",
            code="ROOMCODE26",
        )

    def enter_room(self, code=None):
        return self.client.post(reverse("videos:authorize"), {"code": code or self.plain})

    def test_unified_entry_routes_chat_code_and_invalid_code_is_audited(self):
        response = self.enter_room()
        participant = ChatParticipant.objects.get()
        self.assertRedirects(response, reverse("chat:room", args=[participant.id]))
        self.assertIn(participant.cookie_name, response.cookies)
        self.assertTrue(response.cookies[participant.cookie_name]["httponly"])
        self.assertEqual(response.cookies[participant.cookie_name]["path"], "/")

        invalid = self.client.post(reverse("videos:authorize"), {"code": "INVALID226"})
        self.assertEqual(invalid.status_code, 403)
        self.assertTrue(SecurityEvent.objects.filter(event_type="invalid_code").exists())

    def test_legacy_chat_entry_redirects_to_unified_entry(self):
        response = self.client.get(reverse("chat:entry"))
        self.assertRedirects(response, reverse("videos:access"))

    def test_closed_room_rejects_code(self):
        self.room.is_active = False
        self.room.save()
        response = self.enter_room()
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "对应内容已停止共享", status_code=403)

    def test_room_requires_matching_http_only_token(self):
        participant, token = ChatParticipant.create_for(
            room=self.room,
            ip_address="127.0.0.1",
            user_agent="test",
        )
        url = reverse("chat:room", args=[participant.id])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.cookies[participant.cookie_name] = token
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_chat_room_hides_staff_navigation_after_authorization(self):
        participant, token = ChatParticipant.create_for(
            room=self.room,
            ip_address="127.0.0.1",
            user_agent="staff-visitor",
        )
        staff = get_user_model().objects.create_user(
            "staff-in-chat",
            password="strong-test-password",
            is_staff=True,
        )
        self.client.force_login(staff)
        self.client.cookies[participant.cookie_name] = token
        response = self.client.get(reverse("chat:room", args=[participant.id]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "系统主菜单")
        self.assertContains(response, "退出聊天室")

    def test_participant_can_leave_room_and_cookie_is_cleared(self):
        participant, token = ChatParticipant.create_for(
            room=self.room,
            ip_address="127.0.0.1",
            user_agent="leave-room",
        )
        self.client.cookies[participant.cookie_name] = token
        leave_url = reverse("chat:leave", args=[participant.id])
        self.assertEqual(self.client.get(leave_url).status_code, 405)

        response = self.client.post(leave_url)
        self.assertRedirects(response, reverse("videos:access"))
        participant.refresh_from_db()
        self.assertIsNotNone(participant.revoked_at)
        self.assertEqual(response.cookies[participant.cookie_name]["max-age"], 0)
        self.assertEqual(
            self.client.get(reverse("chat:room", args=[participant.id])).status_code,
            404,
        )

    def test_history_loads_latest_fifty_then_earlier_fifty_without_overlap(self):
        participant, token = ChatParticipant.create_for(
            room=self.room,
            ip_address="127.0.0.1",
            user_agent="test",
        )
        ChatMessage.objects.bulk_create(
            [
                ChatMessage(
                    room=self.room,
                    participant=participant,
                    body=f"消息 {index:03}",
                    client_nonce=uuid.uuid4(),
                )
                for index in range(120)
            ]
        )
        self.client.cookies[participant.cookie_name] = token
        history_url = reverse("chat:history", args=[participant.id])
        latest = self.client.get(history_url).json()
        self.assertEqual(len(latest["messages"]), 50)
        self.assertTrue(latest["has_more"])
        latest_ids = [item["id"] for item in latest["messages"]]
        self.assertEqual(latest_ids, sorted(latest_ids))

        earlier = self.client.get(history_url, {"before": latest_ids[0]}).json()
        self.assertEqual(len(earlier["messages"]), 50)
        self.assertTrue(earlier["has_more"])
        earlier_ids = [item["id"] for item in earlier["messages"]]
        self.assertTrue(set(latest_ids).isdisjoint(earlier_ids))
        self.assertLess(max(earlier_ids), min(latest_ids))

    def test_message_html_is_escaped_on_room_page(self):
        participant, token = ChatParticipant.create_for(
            room=self.room,
            ip_address="127.0.0.1",
            user_agent="test",
        )
        ChatMessage.objects.create(
            room=self.room,
            participant=participant,
            body="<script>alert('xss')</script>",
            client_nonce=uuid.uuid4(),
        )
        self.client.cookies[participant.cookie_name] = token
        response = self.client.get(reverse("chat:room", args=[participant.id]))
        self.assertContains(response, "&lt;script&gt;alert", html=False)
        self.assertNotContains(response, "<script>alert('xss')</script>")

    def test_http_ip_blacklist_blocks_chat_entry(self):
        settings_obj = SystemSettings.load()
        settings_obj.ip_blacklist = r"^127\.0\.0\.1$"
        settings_obj.save()
        response = self.client.get(reverse("videos:access"))
        self.assertEqual(response.status_code, 403)

    def test_each_room_has_one_of_at_least_twenty_nickname_groups(self):
        self.assertGreaterEqual(len(NICKNAME_GROUPS), 20)
        self.assertIn(self.room.nickname_group, NICKNAME_GROUPS)
        first, _ = ChatParticipant.create_for(
            room=self.room,
            ip_address="192.0.2.1",
            user_agent="first",
        )
        second, _ = ChatParticipant.create_for(
            room=self.room,
            ip_address="192.0.2.2",
            user_agent="second",
        )
        self.assertNotEqual(first.display_name, second.display_name)
        self.assertIn(first.display_name, NICKNAME_GROUPS[self.room.nickname_group][1])


@override_settings(
    CHANNEL_LAYERS=TEST_CHANNEL_LAYERS,
    ALLOWED_HOSTS=["testserver"],
)
class ChatWebSocketTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        cache.clear()
        self.room, _ = ChatRoom.create_with_code(name="WebSocket测试")
        self.participant, self.token = ChatParticipant.create_for(
            room=self.room,
            ip_address="127.0.0.1",
            user_agent="test",
        )

    def communicator(self, token=None, client=("127.0.0.1", 50000)):
        cookie_name = self.participant.cookie_name
        return WebsocketCommunicator(
            application,
            f"/ws/chat/{self.participant.id}/",
            headers=[
                (b"host", b"testserver"),
                (b"origin", b"http://testserver"),
                (b"cookie", f"{cookie_name}={token or self.token}".encode()),
            ],
        )

    def test_authorized_socket_saves_and_broadcasts_message(self):
        async def scenario():
            communicator = self.communicator()
            communicator.scope["client"] = ("127.0.0.1", 50000)
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            ready = await communicator.receive_json_from()
            self.assertEqual(ready["type"], "connected")
            nonce = str(uuid.uuid4())
            await communicator.send_json_to(
                {"type": "message", "body": "实时消息", "client_nonce": nonce}
            )
            payload = await communicator.receive_json_from()
            self.assertEqual(payload["type"], "message")
            self.assertEqual(payload["message"]["body"], "实时消息")
            await communicator.disconnect()

        async_to_sync(scenario)()
        self.assertEqual(ChatMessage.objects.count(), 1)

    def test_socket_rejects_missing_token(self):
        async def scenario():
            communicator = WebsocketCommunicator(
                application,
                f"/ws/chat/{self.participant.id}/",
                headers=[
                    (b"host", b"testserver"),
                    (b"origin", b"http://testserver"),
                ],
            )
            communicator.scope["client"] = ("127.0.0.1", 50000)
            connected, code = await communicator.connect()
            self.assertFalse(connected)
            self.assertEqual(code, 4403)

        async_to_sync(scenario)()

    def test_socket_rejects_blacklisted_ip(self):
        settings_obj = SystemSettings.load()
        settings_obj.ip_blacklist = r"^127\.0\.0\.1$"
        settings_obj.save()

        async def scenario():
            communicator = self.communicator()
            communicator.scope["client"] = ("127.0.0.1", 50000)
            connected, code = await communicator.connect()
            self.assertFalse(connected)
            self.assertEqual(code, 4403)

        async_to_sync(scenario)()
