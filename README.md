# 绉佸瘑瑙嗛鎺堟潈鎾斁绯荤粺

涓€涓敤浜庤嚜鎵樼绉佸瘑瑙嗛鍒嗕韩鐨?Django 搴旂敤銆傜鐞嗗憳涓婁紶 MP4 鎴栧皢瑙嗛鏀惧叆鏈嶅姟鍣?`/video` 鐩綍锛岀郴缁熼€氳繃 FFmpeg 杞负鍙椾繚鎶ょ殑 HLS锛屽苟鐢?0浣嶉檺鏃舵巿鏉冪爜鎺у埗鍦ㄧ嚎瑙傜湅銆?
> 娴忚鍣ㄦ挱鏀捐棰戞椂蹇呴』鎺ユ敹濯掍綋鏁版嵁锛屽洜姝ゆ棤娉曟壙璇衡€滅粷瀵逛笉鍙笅杞芥垨褰曞睆鈥濄€傛湰绯荤粺閫氳繃闅旂鍘熸枃浠躲€丠LS鍒嗙墖銆佺煭鏈熺鍚嶃€侀檺娴併€佹按鍗板拰瀹¤鎻愰珮鏈巿鏉冭幏鍙栦笌浼犳挱鎴愭湰銆?
## 涓昏鍔熻兘

- 姣忎釜瑙嗛鍙垱寤哄涓巿鏉冪爜
- 鎺堟潈鐮佹敮鎸佸畨鍏ㄩ殢鏈虹敓鎴愭垨绠＄悊鍛樻墜宸ヨ缃?- 鐙珛璁剧疆鐢熸晥鏃堕棿銆佸け鏁堟椂闂村拰澶囨敞
- 鍒犻櫎鎺堟潈鐮佸悗绔嬪嵆鎾ら攢鍏舵椿鍔ㄦ挱鏀句細璇?- 绠＄悊绔笂浼?MP4锛屾牎楠屽鍣ㄥ拰瑙嗛杞ㄩ亾
- 鑷畾涔夎棰戞樉绀哄悕绉帮紝涓嶆毚闇叉棤鎰忎箟鐨勭墿鐞嗘枃浠跺悕
- 姣忓垎閽熸壂鎻?`/video`锛孋elery涓嶧Fmpeg寮傛杞爜
- 鍔ㄦ€侀噸鍐橦LS娓呭崟锛屽獟浣撹祫婧愪娇鐢ㄧ煭鏈熺鍚?- 璁板綍鎺堟潈鏃堕棿銆両P銆佽鐪嬫椂闀裤€佽繘搴﹀拰鎾斁浜嬩欢
- 瑙傜湅璁板綍鍒嗛〉鏌ヨ
- 鑷畾涔夌郴缁熷悕绉般€佺鐞嗗憳鑷姪淇敼瀵嗙爜
- 绠＄悊鍛樻搷浣滀笌瀹夊叏浜嬩欢瀹¤

## 鎶€鏈爤

- Django 5 / Python 3.11+
- MySQL 8
- Redis / Celery
- FFmpeg / FFprobe
- Gunicorn / Nginx / systemd

鐢熶骇閮ㄧ讲涓鸿８鏈烘湇鍔★紝涓嶄緷璧?Docker銆傛湰鍦版祴璇曢粯璁や娇鐢⊿QLite銆?
## 蹇€熷紑濮?
```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python manage.py migrate
.venv\Scripts\python manage.py createsuperuser
.venv\Scripts\python manage.py runserver
```

鎵撳紑锛?
- `http://127.0.0.1:8000/`锛氭巿鏉冭鐪嬪叆鍙?- `http://127.0.0.1:8000/manage/`锛氱鐞嗘帶鍒跺彴
- `http://127.0.0.1:8000/admin/`锛欴jango绯荤粺绠＄悊

鏈湴鏈缃?`DB_ENGINE=mysql` 鏃朵娇鐢⊿QLite锛屼粎鐢ㄤ簬寮€鍙戝拰娴嬭瘯銆?
## 鏂囨。

- [绯荤粺鏋舵瀯](docs/ARCHITECTURE.md)
- [瑁告満閮ㄧ讲鎵嬪唽](docs/DEPLOYMENT.md)
- [鏁版嵁搴撳垵濮嬪寲涓庣淮鎶(docs/DATABASE.md)
- [绠＄悊鍛樻搷浣滄墜鍐宂(docs/OPERATIONS.md)
- [璐＄尞鎸囧崡](CONTRIBUTING.md)
- [瀹夊叏绛栫暐](SECURITY.md)
- [鑷姩鍖栦唬鐞嗙害瀹歖(AGENTS.md)
- [鍙樻洿璁板綍](CHANGELOG.md)

## 鐢熶骇鍒濆鍖?
1. 浣跨敤 `deploy/mysql/init.sql` 鍒涘缓MySQL鏁版嵁搴撲笌搴旂敤鐢ㄦ埛銆?2. 澶嶅埗骞跺～鍐?`deploy/private-video.env.example`銆?3. 瀹夎渚濊禆骞舵墽琛孌jango杩佺Щ銆?4. 瀹夎 `deploy/` 涓嬬殑systemd鍜孨ginx閰嶇疆銆?5. 杩愯 `deploy/smoke_test.sh`銆?
瀹屾暣姝ラ瑙?[閮ㄧ讲鎵嬪唽](docs/DEPLOYMENT.md)銆?
## 娴嬭瘯

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test -v 2
```

GitHub Actions宸ヤ綔娴佷細鎵ц鐩稿悓妫€鏌ャ€傚伐浣滄祦鍙娇鐢⊿QLite娴嬭瘯锛屼笉浼氳繛鎺ョ敓浜ф暟鎹簱銆?
## 浠撳簱瀹夊叏

鎻愪氦鍓嶇‘璁ゆ湭鍖呭惈锛?
- 鐢熶骇鏈嶅姟鍣↖P銆佸煙鍚嶅拰鐜鏂囦欢
- 鏁版嵁搴撱€丷edis鎴栫鐞嗗憳瀵嗙爜
- 鎺堟潈鐮併€丆ookie銆佺閽ュ拰鏁版嵁搴撹浆鍌?- 鍘熷瑙嗛銆丠LS銆佹棩蹇楀拰鏈劚鏁忔埅鍥?
鐢熶骇鍑嵁搴斿彧淇濆瓨鍦ㄦ湇鍔″櫒鐨勬潈闄愬彈闄愭枃浠朵腑銆?
## 璁稿彲璇?
鏈」鐩噰鐢?[MIT License](LICENSE)銆?
