from django import forms

from videos.models import normalize_access_code
from videos.code_registry import code_digest_in_use

from .nicknames import NICKNAME_GROUP_CHOICES


class ChatRoomForm(forms.Form):
    name = forms.CharField(
        label="聊天室名称",
        max_length=120,
        widget=forms.TextInput(
            attrs={"class": "form-control", "autocomplete": "off", "placeholder": "例如：项目讨论组"}
        ),
    )
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
                "placeholder": "10位英文字母或数字",
            }
        ),
    )
    nickname_group = forms.ChoiceField(
        label="备用昵称组",
        choices=(("auto", "系统随机选择"),) + NICKNAME_GROUP_CHOICES,
        initial="auto",
        required=False,
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    def __init__(self, *args, room=None, **kwargs):
        self.room = room
        super().__init__(*args, **kwargs)
        if room:
            self.fields.pop("name")
            self.fields.pop("nickname_group")

    def clean_custom_code(self):
        value = self.cleaned_data.get("custom_code", "")
        if self.cleaned_data.get("code_mode") != "manual":
            return ""
        plain = normalize_access_code(value)
        if len(plain) != 10:
            raise forms.ValidationError("手工授权码必须为10位英文字母或数字")
        from videos.models import digest_access_code

        if code_digest_in_use(
            digest_access_code(plain),
            exclude_chat_room_id=self.room.pk if self.room else None,
        ):
            raise forms.ValidationError("该授权码已被其他内容使用，请更换一个")
        return plain

    def clean_name(self):
        return self.cleaned_data["name"].strip()

    def clean_nickname_group(self):
        return self.cleaned_data.get("nickname_group") or "auto"
