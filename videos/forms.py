from django import forms
from django.conf import settings
from django.contrib.auth.forms import PasswordChangeForm
from django.utils import timezone

from .ip_access import is_ip_blocked, normalize_ip_blacklist
from .models import AccessCode, SystemSettings, digest_access_code, normalize_access_code


class AccessCodeForm(forms.Form):
    code_mode = forms.ChoiceField(
        label="授权码生成方式",
        choices=(("auto", "自动生成"), ("manual", "手工设置")),
        initial="auto",
        widget=forms.RadioSelect,
    )
    custom_code = forms.CharField(
        label="自定义授权码",
        required=False,
        min_length=10,
        max_length=20,
        widget=forms.TextInput(
            attrs={
                "class": "form-control manual-code-input",
                "autocomplete": "off",
                "autocapitalize": "characters",
                "spellcheck": "false",
                "placeholder": "输入10位英文字母或数字",
            }
        ),
    )
    expires_at = forms.DateTimeField(
        label="失效时间",
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={"type": "datetime-local", "class": "form-control"},
        ),
        input_formats=["%Y-%m-%dT%H:%M"],
    )
    starts_at = forms.DateTimeField(
        label="生效时间",
        required=False,
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={"type": "datetime-local", "class": "form-control"},
        ),
        input_formats=["%Y-%m-%dT%H:%M"],
    )
    note = forms.CharField(
        label="备注",
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "例如：客户A、项目验收、内部培训"}
        ),
    )
    quantity = forms.IntegerField(
        label="生成数量",
        min_value=1,
        max_value=20,
        initial=1,
        widget=forms.NumberInput(attrs={"class": "form-control quantity-input", "min": 1, "max": 20}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            now = timezone.localtime().replace(second=0, microsecond=0)
            self.initial.setdefault("starts_at", now)
            self.initial.setdefault("expires_at", now + timezone.timedelta(days=7))

    def clean_starts_at(self):
        return self.cleaned_data.get("starts_at") or timezone.now()

    def clean(self):
        cleaned = super().clean()
        starts_at = cleaned.get("starts_at")
        expires_at = cleaned.get("expires_at")
        if starts_at and expires_at and expires_at <= starts_at:
            self.add_error("expires_at", "失效时间必须晚于生效时间")
        if cleaned.get("code_mode") == "manual":
            plain = normalize_access_code(cleaned.get("custom_code"))
            if len(plain) != 10:
                self.add_error("custom_code", "手工授权码必须为10位英文字母或数字")
            elif AccessCode.objects.filter(code_digest=digest_access_code(plain)).exists():
                self.add_error("custom_code", "该授权码已使用过，请更换一个")
            else:
                cleaned["custom_code"] = plain
            cleaned["quantity"] = 1
        return cleaned


class VideoTitleForm(forms.Form):
    title = forms.CharField(
        label="视频名称",
        max_length=255,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "例如：2026年产品介绍",
                "autocomplete": "off",
            }
        ),
    )

    def clean_title(self):
        title = self.cleaned_data["title"].strip()
        if not title:
            raise forms.ValidationError("请输入视频名称")
        return title


class VideoUploadForm(VideoTitleForm):
    video_file = forms.FileField(
        label="MP4视频文件",
        widget=forms.FileInput(attrs={"class": "file-input", "accept": ".mp4,video/mp4"}),
    )

    def clean_video_file(self):
        uploaded = self.cleaned_data["video_file"]
        if not uploaded.name.lower().endswith(".mp4"):
            raise forms.ValidationError("仅允许上传 .mp4 格式的视频")
        if uploaded.size <= 0:
            raise forms.ValidationError("上传文件不能为空")
        if uploaded.size > settings.MAX_VIDEO_UPLOAD_BYTES:
            limit_gb = settings.MAX_VIDEO_UPLOAD_BYTES / (1024 ** 3)
            raise forms.ValidationError(f"视频大小不能超过 {limit_gb:g} GB")
        header = uploaded.read(32)
        uploaded.seek(0)
        if len(header) < 12 or header[4:8] != b"ftyp":
            raise forms.ValidationError("文件不是有效的 MP4 容器")
        return uploaded


class SystemSettingsForm(forms.ModelForm):
    class Meta:
        model = SystemSettings
        fields = ("system_name",)
        widgets = {
            "system_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "例如：企业培训视频中心",
                    "autocomplete": "organization",
                }
            )
        }

    def clean_system_name(self):
        name = self.cleaned_data["system_name"].strip()
        if not name:
            raise forms.ValidationError("请输入系统名称")
        return name


class IPBlacklistForm(forms.ModelForm):
    class Meta:
        model = SystemSettings
        fields = ("ip_blacklist",)
        widgets = {
            "ip_blacklist": forms.Textarea(
                attrs={
                    "class": "form-control ip-blacklist-input",
                    "rows": 9,
                    "spellcheck": "false",
                    "placeholder": (
                        "每行一条正则表达式，例如：\n"
                        r"^203\.0\.113\.25$" "\n"
                        r"^198\.51\.100\.\d{1,3}$"
                    ),
                }
            )
        }

    def __init__(self, *args, current_ip=None, **kwargs):
        self.current_ip = current_ip
        super().__init__(*args, **kwargs)

    def clean_ip_blacklist(self):
        try:
            blacklist = normalize_ip_blacklist(self.cleaned_data["ip_blacklist"])
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc
        if self.current_ip and is_ip_blocked(self.current_ip, blacklist):
            raise forms.ValidationError(
                f"规则会命中当前管理IP（{self.current_ip}），为避免锁定管理员，无法保存"
            )
        return blacklist


class StyledPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        placeholders = {
            "old_password": "输入当前管理员密码",
            "new_password1": "输入新密码",
            "new_password2": "再次输入新密码",
        }
        for name, field in self.fields.items():
            field.widget.attrs.update(
                {
                    "class": "form-control",
                    "placeholder": placeholders[name],
                    "autocomplete": "current-password" if name == "old_password" else "new-password",
                }
            )


class CodeEntryForm(forms.Form):
    code = forms.CharField(
        label="查看授权码",
        min_length=10,
        max_length=14,
        widget=forms.TextInput(
            attrs={
                "class": "code-input",
                "autocomplete": "one-time-code",
                "autocapitalize": "characters",
                "spellcheck": "false",
                "placeholder": "请输入10位授权码",
            }
        ),
    )

    def clean_code(self):
        code = normalize_access_code(self.cleaned_data["code"])
        if len(code) != 10:
            raise forms.ValidationError("请输入完整的10位授权码")
        return code
