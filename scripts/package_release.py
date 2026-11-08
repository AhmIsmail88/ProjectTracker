"""Create a shareable ZIP using an explicit file allowlist, without local data."""
from pathlib import Path
import argparse
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from constants import APP_VERSION

GUIDE = '''Project Tracker {version} — Windows

التشغيل:
1. فك ضغط الحزمة بالكامل في مجلد عادي، ثم شغّل ProjectTracker.exe.
2. اختر مجلد حفظ البيانات عند التشغيل الأول، ثم أنشئ حساب المدير وكلمة مروره.
3. لا يلزم تثبيت Python أو خط Cairo. النسخة مخصصة لنظام Windows 64-bit.
4. لمشاركة البرنامج فقط أرسل ملف ZIP هذا. لا يحتوي على مشاريع أو حسابات أو مفاتيح شخصية.

المستخدمون والصلاحيات:
من شاشة المشاريع > المزيد > المستخدمون، أنشئ حسابات المهندسين وعيّن مشاريعهم.
المدير يدير جميع المشاريع؛ المهندس يعدّل المشاريع المسندة إليه فقط.
الحسابات تتبع مجلد البيانات؛ الانتقال إلى مجلد آخر يتطلب تسجيل الدخول لحساباته.
إذا نقلت نسخة احتياطية، استخدم حساباتها القائمة بدل إنشاء مدير جديد.

المساعد الذكي:
افتح «المساعد الذكي» ثم «إعدادات المساعد». أدخل مفتاح OpenRouter الخاص بك.
يمكن إنشاء المفتاح من https://openrouter.ai/keys
النموذج الافتراضي openrouter/free، ويمكن تغييره إلى نموذج آخر متاح لحسابك.
اضغط «اختبار اتصال المساعد» قبل الاستخدام. يلزم الإنترنت ومفتاح صالح؛ حدود
الاستخدام وتوافر النماذج تعتمد على الخدمة. تُحفظ إعدادات المساعد لحساب Windows
المستخدم، وتظل متاحة بعد نقل البرنامج إلى مجلد آخر على نفس الجهاز.
على جهاز آخر أدخل مفتاح المستلم من إعدادات المساعد؛ المفتاح لا ينتقل مع EXE.
لا تشارك ملف .env بمفتاحك الشخصي.
عند طرح سؤال تُرسل بيانات النطاق المختار إلى OpenRouter للإجابة عنه.

نقل مشاريعك إلى جهاز آخر:
استخدم File > Backup Now لإنشاء نسخة تشمل قاعدة البيانات والمرفقات.
فك النسخة في مجلد على الجهاز الآخر واختره كمجلد بيانات البرنامج.
لا تكتفِ بنقل ملف قاعدة البيانات وحده إذا كانت هناك مرفقات.

الواجهة:
خط Cairo مضمّن للعربية والإنجليزية. شاشة المرفقات قابلة للتكبير والتصغير،
ويمكن سحب الفاصل لتغيير مساحة قائمة الملفات والمعاينة.

فحص التثبيت الاختياري (لا يفتح بيانات المشاريع):
ProjectTracker.exe --check-installation report.json
أضف --test-ai لاختبار الاتصال برسالة تجريبية قصيرة.
'''


def package(executable, output):
    output.mkdir(parents=True, exist_ok=True)
    name = f"ProjectTracker-{APP_VERSION}-Windows"
    folder = output / name
    folder.mkdir(exist_ok=True)
    allowed = {'ProjectTracker.exe', 'README-AR.txt', '.env.example', 'OFL-Cairo.txt'}
    unexpected = {p.name for p in folder.iterdir()} - allowed
    if unexpected:
        raise RuntimeError('Release folder contains unexpected files; use an empty output folder.')
    shutil.copy2(executable, folder / 'ProjectTracker.exe')
    shutil.copy2(ROOT / 'assets/fonts/OFL-Cairo.txt', folder / 'OFL-Cairo.txt')
    shutil.copy2(ROOT / '.env.example', folder / '.env.example')
    (folder / 'README-AR.txt').write_text(GUIDE.format(version=APP_VERSION), encoding='utf-8-sig')
    archive = output / f'{name}.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for filename in sorted(allowed):
            bundle.write(folder / filename, f'{name}/{filename}')
    return archive


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    print(package(args.exe, args.output))
