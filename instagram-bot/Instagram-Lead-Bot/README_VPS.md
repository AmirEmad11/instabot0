# 🚀 دليل نشر Instagram Lead Bot على VPS

## المتطلبات

| المتطلب | الحد الأدنى |
|---------|------------|
| نظام التشغيل | Ubuntu 22.04 LTS |
| RAM | 2 GB |
| CPU | 1 vCPU |
| مساحة القرص | 5 GB |
| الشبكة | IP ثابت + بورت 8081 مفتوح |

---

## الخطوة الأولى: رفع الملفات على السيرفر

```bash
# على جهازك المحلي — ارفع المجلد كاملاً عبر scp
scp -r Instagram-Lead-Bot/ root@YOUR_SERVER_IP:/root/

# أو عبر git clone إذا الكود على GitHub
ssh root@YOUR_SERVER_IP
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
cd YOUR_REPO/Instagram-Lead-Bot
```

---

## الخطوة الثانية: تشغيل سكريبت التثبيت

```bash
# تأكد إنك داخل مجلد Instagram-Lead-Bot
cd /root/Instagram-Lead-Bot

# شغّل السكريبت بصلاحيات root
sudo bash vps_deploy.sh
```

> السكريبت هيقوم بـ:
> - تثبيت Python 3 والـ virtual environment
> - تثبيت كل system dependencies لـ Chromium
> - تثبيت Playwright والمكتبات
> - إنشاء مستخدم نظام مخصص `instabot`
> - ضبط الصلاحيات وملفات السجل
> - تثبيت وتفعيل الخدمة تلقائياً

---

## الخطوة الثالثة: التحقق من التشغيل

```bash
# تحقق من حالة الخدمة
sudo systemctl status instabot

# شاهد السجل المباشر (Ctrl+C للخروج)
sudo journalctl -fu instabot
```

إذا ظهرت **● instabot.service — active (running)** الخدمة شغالة ✅

---

## الوصول للتطبيق

افتح المتصفح على:
```
http://YOUR_SERVER_IP:8081
```

---

## أوامر إدارة الخدمة

```bash
# حالة الخدمة
sudo systemctl status instabot

# إعادة التشغيل (بعد تعديل الكود)
sudo systemctl restart instabot

# إيقاف الخدمة
sudo systemctl stop instabot

# بدء الخدمة
sudo systemctl start instabot

# تعطيل التشغيل التلقائي
sudo systemctl disable instabot

# تفعيل التشغيل التلقائي مع الـ boot
sudo systemctl enable instabot
```

---

## متابعة ملفات السجل

```bash
# سجل الأخطاء (الأهم)
tail -f /var/log/instabot/server_errors.log

# سجل الوصول الكامل
tail -f /var/log/instabot/access.log

# آخر 100 سطر من سجل النظام للخدمة
sudo journalctl -u instabot -n 100 --no-pager

# سجل مباشر (live)
sudo journalctl -fu instabot
```

---

## تحديث الكود (بعد تعديلات جديدة)

```bash
# 1. ارفع الكود الجديد (مثال: عبر git)
cd /root/Instagram-Lead-Bot
git pull

# 2. انسخ الملفات المحدّثة لمجلد التطبيق
sudo rsync -a --delete instagram_automation/ /opt/instabot/instagram_automation/
sudo chown -R instabot:instabot /opt/instabot/instagram_automation/

# 3. أعد تشغيل الخدمة
sudo systemctl restart instabot

# 4. تحقق من التشغيل
sudo systemctl status instabot
```

---

## تغيير البورت

```bash
# عدّل ملف متغيرات البيئة
sudo nano /opt/instabot/.env
# غيّر السطر: PORT=8081  →  PORT=رقم_البورت_الجديد

# عدّل ملف الخدمة
sudo nano /etc/systemd/system/instabot.service
# غيّر --server.port 8081  →  --server.port رقم_البورت_الجديد

# أعد تحميل وتشغيل
sudo systemctl daemon-reload
sudo systemctl restart instabot
```

---

## إذا لم تشتغل الخدمة

```bash
# اقرأ تفاصيل الخطأ
sudo journalctl -u instabot -n 50 --no-pager

# تحقق من ملف الأخطاء
cat /var/log/instabot/server_errors.log

# تحقق من تثبيت Playwright
/opt/instabot/venv/bin/playwright --version

# تحقق من Chromium
/opt/instabot/venv/bin/playwright install chromium --dry-run
```

---

## إعداد Nginx كـ Reverse Proxy (اختياري)

إذا أردت الوصول عبر البورت 80 أو 443 مع HTTPS:

```bash
sudo apt-get install -y nginx certbot python3-certbot-nginx

# أنشئ ملف إعدادات Nginx
sudo nano /etc/nginx/sites-available/instabot
```

```nginx
server {
    listen 80;
    server_name YOUR_DOMAIN.com;

    location / {
        proxy_pass http://127.0.0.1:8081;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/instabot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx

# HTTPS مجاني عبر Let's Encrypt
sudo certbot --nginx -d YOUR_DOMAIN.com
```

---

## هيكل الملفات بعد التثبيت

```
/opt/instabot/
├── instagram_automation/     ← كود التطبيق
│   ├── streamlit_app.py
│   ├── site_users.db         ← قاعدة بيانات المستخدمين
│   ├── leads.db              ← قاعدة بيانات العملاء
│   ├── sessions/             ← جلسات Instagram لكل مستخدم
│   ├── screenshots/          ← لقطات الشاشة عند الأخطاء
│   └── server_errors.log     ← سجل أخطاء التطبيق
├── venv/                     ← البيئة الافتراضية Python
├── playwright_browsers/      ← Chromium
└── .env                      ← متغيرات البيئة

/var/log/instabot/
├── access.log                ← سجل الوصول
└── server_errors.log         ← سجل الأخطاء (systemd)
```
