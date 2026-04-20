#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  vps_deploy.sh — Instagram Lead Bot | Ubuntu 22.04 VPS Setup
#  الاستخدام:  sudo bash vps_deploy.sh
# ══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── ألوان للـ output ──
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ══════════════════════════════════════════════════════════════════════════════
#  0. التحقق من الصلاحيات ونظام التشغيل
# ══════════════════════════════════════════════════════════════════════════════
[[ "$EUID" -ne 0 ]] && error "شغّل السكريبت بصلاحيات root: sudo bash vps_deploy.sh"
. /etc/os-release
[[ "$ID" != "ubuntu" ]] && warn "السكريبت مُخصّص لـ Ubuntu – قد تحتاج تعديلات لتوزيعات أخرى"

info "══════════════════════════════════════════"
info "   Instagram Lead Bot — VPS Deployment"
info "══════════════════════════════════════════"

# ══════════════════════════════════════════════════════════════════════════════
#  1. الإعدادات — عدّل هذه القيم قبل التشغيل
# ══════════════════════════════════════════════════════════════════════════════
APP_USER="${APP_USER:-instabot}"                                  # مستخدم Linux للسيرفر
APP_DIR="${APP_DIR:-/opt/instabot}"                               # مجلد التثبيت
REPO_DIR="${REPO_DIR:-$(pwd)}"                                    # مجلد الكود (افتراضياً المجلد الحالي)
VENV_DIR="$APP_DIR/venv"                                          # مجلد البيئة الافتراضية
LOG_DIR="/var/log/instabot"                                       # مجلد ملفات السجل
PORT="${PORT:-8081}"                                              # البورت

info "إعدادات التثبيت:"
echo "  APP_USER  = $APP_USER"
echo "  APP_DIR   = $APP_DIR"
echo "  REPO_DIR  = $REPO_DIR"
echo "  PORT      = $PORT"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
#  2. تحديث النظام وتثبيت الأدوات الأساسية
# ══════════════════════════════════════════════════════════════════════════════
info "تحديث قوائم الحزم..."
apt-get update -qq

info "تثبيت الأدوات الأساسية..."
apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv python3-dev \
    git curl wget unzip ca-certificates \
    build-essential libssl-dev libffi-dev \
    supervisor logrotate

success "تم تثبيت الأدوات الأساسية"

# ══════════════════════════════════════════════════════════════════════════════
#  3. system dependencies لـ Playwright / Chromium على Linux
#     (مطلوبة حتى في headless mode)
# ══════════════════════════════════════════════════════════════════════════════
info "تثبيت متطلبات Chromium (Playwright system dependencies)..."
apt-get install -y --no-install-recommends \
    libnss3 libnss3-dev libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2 \
    libpango-1.0-0 libpangocairo-1.0-0 libcairo2 \
    libglib2.0-0 libx11-6 libxext6 libxss1 libxtst6 \
    libdbus-1-3 libxcb1 libxcb-dri3-0 libxcb-icccm4 \
    libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 \
    libxcb-shape0 libxcb-sync1 libxcb-xfixes0 libxcb-xinerama0 \
    libxcb-xkb1 libxkbcommon-x11-0 \
    fonts-liberation fonts-noto fonts-noto-cjk \
    libvulkan1 libgl1-mesa-glx libgl1 \
    xvfb

success "تم تثبيت متطلبات Chromium"

# ══════════════════════════════════════════════════════════════════════════════
#  4. إنشاء مستخدم النظام المخصص
# ══════════════════════════════════════════════════════════════════════════════
if ! id -u "$APP_USER" &>/dev/null; then
    info "إنشاء مستخدم النظام: $APP_USER"
    useradd --system --shell /bin/bash --create-home "$APP_USER"
    success "تم إنشاء المستخدم $APP_USER"
else
    info "المستخدم $APP_USER موجود بالفعل"
fi

# ══════════════════════════════════════════════════════════════════════════════
#  5. نسخ ملفات التطبيق وإعداد المجلدات
# ══════════════════════════════════════════════════════════════════════════════
info "إعداد مجلد التطبيق: $APP_DIR"
mkdir -p "$APP_DIR"

BOT_SRC="$REPO_DIR/instagram_automation"
[[ ! -d "$BOT_SRC" ]] && error "لم أجد مجلد instagram_automation في: $REPO_DIR"

info "نسخ ملفات البوت..."
rsync -a --delete "$BOT_SRC/" "$APP_DIR/instagram_automation/"

# المجلدات الضرورية
mkdir -p "$APP_DIR/instagram_automation/sessions"
mkdir -p "$APP_DIR/instagram_automation/screenshots"
mkdir -p "$LOG_DIR"

success "تم نسخ ملفات التطبيق"

# ══════════════════════════════════════════════════════════════════════════════
#  6. إنشاء البيئة الافتراضية Python وتثبيت المكتبات
# ══════════════════════════════════════════════════════════════════════════════
info "إنشاء البيئة الافتراضية Python..."
python3 -m venv "$VENV_DIR"

info "تثبيت مكتبات Python..."
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install --quiet \
    streamlit>=1.35.0 \
    playwright>=1.45.0 \
    aiosqlite>=0.20.0 \
    openpyxl>=3.1.0

success "تم تثبيت مكتبات Python"

# ══════════════════════════════════════════════════════════════════════════════
#  7. تثبيت Chromium عبر Playwright
# ══════════════════════════════════════════════════════════════════════════════
info "تثبيت Chromium عبر Playwright..."
PLAYWRIGHT_BROWSERS_PATH="$APP_DIR/playwright_browsers" \
"$VENV_DIR/bin/playwright" install chromium
success "تم تثبيت Chromium"

# ══════════════════════════════════════════════════════════════════════════════
#  8. ضبط متغيرات البيئة (Environment Variables)
# ══════════════════════════════════════════════════════════════════════════════
info "كتابة ملف متغيرات البيئة..."
ENV_FILE="$APP_DIR/.env"
cat > "$ENV_FILE" <<ENVEOF
# ── Instagram Lead Bot — Environment Variables ──
# عدّل هذا الملف بعد التثبيت إذا احتجت إعدادات مخصصة

PORT=$PORT
PYTHONUNBUFFERED=1
PYTHONDONTWRITEBYTECODE=1
STREAMLIT_SERVER_HEADLESS=true
STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# مسار المتصفح (Playwright)
PLAYWRIGHT_BROWSERS_PATH=$APP_DIR/playwright_browsers

# مسار ملفات السجل
LOG_FILE=$LOG_DIR/server_errors.log
ENVEOF

success "تم إنشاء ملف .env"

# ══════════════════════════════════════════════════════════════════════════════
#  9. ضبط الصلاحيات
# ══════════════════════════════════════════════════════════════════════════════
info "ضبط صلاحيات الملفات..."
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"
chown -R "$APP_USER":"$APP_USER" "$LOG_DIR"

# قاعدة البيانات والسشنات والسجلات
chmod 750 "$APP_DIR/instagram_automation/sessions"
chmod 750 "$APP_DIR/instagram_automation/screenshots"
chmod 640 "$ENV_FILE"

# السماح لـ root بالقراءة (للـ systemd)
chmod 755 "$APP_DIR"
chmod 755 "$APP_DIR/instagram_automation"

success "تم ضبط الصلاحيات"

# ══════════════════════════════════════════════════════════════════════════════
#  10. إنشاء ملف systemd service
# ══════════════════════════════════════════════════════════════════════════════
info "تثبيت systemd service..."
SERVICE_FILE="/etc/systemd/system/instabot.service"
cat > "$SERVICE_FILE" <<SVCEOF
[Unit]
Description=Instagram Lead Bot — Streamlit SaaS Panel
Documentation=file://$APP_DIR/README_VPS.md
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR/instagram_automation

EnvironmentFile=$APP_DIR/.env
Environment="PLAYWRIGHT_BROWSERS_PATH=$APP_DIR/playwright_browsers"
Environment="PATH=$VENV_DIR/bin:/usr/local/bin:/usr/bin:/bin"

ExecStart=$VENV_DIR/bin/streamlit run streamlit_app.py \
    --server.port $PORT \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false

Restart=always
RestartSec=10
StartLimitIntervalSec=120
StartLimitBurst=5

# السجلات
StandardOutput=append:$LOG_DIR/access.log
StandardError=append:$LOG_DIR/server_errors.log

# أمان إضافي
NoNewPrivileges=yes
ProtectSystem=full
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable instabot.service
success "تم تثبيت وتفعيل instabot.service"

# ══════════════════════════════════════════════════════════════════════════════
#  11. إعداد logrotate لمنع امتلاء ملفات السجل
# ══════════════════════════════════════════════════════════════════════════════
info "إعداد logrotate..."
cat > /etc/logrotate.d/instabot <<LREOF
$LOG_DIR/*.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
    copytruncate
    su $APP_USER $APP_USER
}
LREOF
success "تم إعداد logrotate (14 يوم احتفاظ)"

# ══════════════════════════════════════════════════════════════════════════════
#  12. فتح البورت في جدار الحماية (ufw) إن كان مثبتاً
# ══════════════════════════════════════════════════════════════════════════════
if command -v ufw &>/dev/null && ufw status | grep -q "Status: active"; then
    info "فتح البورت $PORT في جدار الحماية (ufw)..."
    ufw allow "$PORT/tcp" comment "Instagram Lead Bot"
    success "تم فتح البورت $PORT"
else
    warn "ufw غير مثبت أو غير مفعّل — تأكد من فتح البورت $PORT يدوياً"
fi

# ══════════════════════════════════════════════════════════════════════════════
#  13. تشغيل الخدمة
# ══════════════════════════════════════════════════════════════════════════════
info "تشغيل الخدمة..."
systemctl start instabot.service
sleep 3

if systemctl is-active --quiet instabot.service; then
    success "الخدمة تعمل بنجاح ✅"
else
    warn "الخدمة لم تبدأ — شوف الأخطاء:"
    journalctl -u instabot.service -n 30 --no-pager
fi

# ══════════════════════════════════════════════════════════════════════════════
#  ملخص التثبيت
# ══════════════════════════════════════════════════════════════════════════════
SERVER_IP=$(curl -s https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')
echo ""
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo -e "${GREEN}   ✅ التثبيت اكتمل بنجاح!${NC}"
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo ""
echo "  🌐 الرابط:        http://$SERVER_IP:$PORT"
echo "  📁 مجلد التطبيق:  $APP_DIR"
echo "  📋 ملفات السجل:   $LOG_DIR/"
echo "  🔧 متغيرات البيئة: $APP_DIR/.env"
echo ""
echo "  أوامر مفيدة:"
echo "    sudo systemctl status instabot     # حالة الخدمة"
echo "    sudo systemctl restart instabot    # إعادة تشغيل"
echo "    sudo journalctl -fu instabot       # سجل مباشر"
echo "    tail -f $LOG_DIR/server_errors.log # سجل الأخطاء"
echo ""
