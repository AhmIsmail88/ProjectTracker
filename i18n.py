"""
i18n.py
Minimal, dependency-free translation layer. Not a full Qt Linguist setup —
just a lookup table + a helper, which is enough for an internal tool with a
bounded set of screens. Switching language rebuilds the UI text (see
main.py: MainWindow._rebuild_ui) rather than trying to patch every widget
individually.
"""

STRINGS = {
    "app_title": {"en": "Project Tracker", "ar": "متابعة المشاريع"},
    "projects": {"en": "Projects", "ar": "المشاريع"},
    "suppliers": {"en": "Suppliers", "ar": "الموردين"},
    "ai_assistant": {"en": "AI Assistant", "ar": "المساعد الذكي"},
    "dashboard": {"en": "Dashboard", "ar": "لوحة المتابعة"},
    "items_tracker": {"en": "Items / BOQ Tracker", "ar": "البنود / الحصر"},
    "reports": {"en": "Reports", "ar": "التقارير"},
    "back_to_projects": {"en": "\u2190 Back to Projects", "ar": "\u2192 رجوع للمشاريع"},
    "add": {"en": "Add", "ar": "إضافة"},
    "edit": {"en": "Edit", "ar": "تعديل"},
    "delete": {"en": "Delete", "ar": "حذف"},
    "search": {"en": "Search...", "ar": "بحث..."},
    "search_projects": {"en": "Search by project name or number...", "ar": "بحث باسم المشروع أو رقمه..."},
    "search_items": {"en": "Search items by name...", "ar": "بحث في البنود بالاسم..."},
    "all_statuses": {"en": "All Statuses", "ar": "كل الحالات"},
    "all_suppliers": {"en": "All Suppliers", "ar": "كل الموردين"},
    "all_areas": {"en": "All Areas", "ar": "كل الأماكن"},
    "add_item": {"en": "+ Add Item", "ar": "+ إضافة بند"},
    "edit_item": {"en": "Edit Item", "ar": "تعديل البند"},
    "delete_item": {"en": "Delete Item", "ar": "حذف البند"},
    "duplicate": {"en": "Duplicate (Next Row)", "ar": "تكرار (سطر جديد)"},
    "attachments": {"en": "Attachments (PR/PO/Ref)", "ar": "المرفقات (طلب/أمر شراء/مرجع)"},
    "move_up": {"en": "Move Up", "ar": "تحريك لأعلى"},
    "move_down": {"en": "Move Down", "ar": "تحريك لأسفل"},
    "move": {"en": "Move", "ar": "نقل"},
    "new_project": {"en": "New Project", "ar": "مشروع جديد"},
    "edit_project": {"en": "Edit Project", "ar": "تعديل المشروع"},
    "open_project": {"en": "Open", "ar": "فتح"},
    "trash": {"en": "Trash", "ar": "سلة المحذوفات"},
    "undo": {"en": "Undo", "ar": "تراجع"},
    "language": {"en": "Language: العربية", "ar": "Language: English"},
    "dark_mode": {"en": "\U0001F319 Dark Mode", "ar": "\U0001F319 الوضع الداكن"},
    "light_mode": {"en": "\u2600\ufe0f Light Mode", "ar": "\u2600\ufe0f الوضع الفاتح"},
    "export_excel": {"en": "Export to Excel (.xlsx)", "ar": "تصدير إلى إكسل (.xlsx)"},
    "export_pdf": {"en": "Export to PDF report (with chart)", "ar": "تصدير تقرير PDF (مع رسم بياني)"},
    "no_project_selected": {"en": "No project selected", "ar": "لم يتم اختيار مشروع"},
    "select_project_first": {"en": "Select a project first.", "ar": "اختر مشروعًا أولاً."},
    "quick_report": {"en": "Quick Report (.txt)", "ar": "تقرير سريع (txt)"},
    "save_as_txt": {"en": "Save last reply as .txt", "ar": "حفظ آخر رد كملف txt"},
    "activity": {"en": "Activity Log", "ar": "سجل التغييرات"},
    "history": {"en": "History", "ar": "السجل"},
    "new_conversation": {"en": "New Conversation", "ar": "محادثة جديدة"},
    "menu_file": {"en": "&File", "ar": "&ملف"},
    "menu_open_data_folder": {"en": "Open Data Folder", "ar": "فتح مجلد البيانات"},
    "menu_change_data_folder": {"en": "Change Data Folder...", "ar": "تغيير مجلد البيانات..."},
    "menu_backup_now": {"en": "Backup Now...", "ar": "نسخ احتياطي الآن..."},
    "menu_exit": {"en": "Exit", "ar": "خروج"},
    "menu_help": {"en": "&Help", "ar": "&مساعدة"},
    "menu_keyboard_shortcuts": {"en": "Keyboard Shortcuts", "ar": "اختصارات لوحة المفاتيح"},
    "menu_company_logo": {"en": "Company Logo...", "ar": "شعار الشركة..."},
    "menu_remove_logo": {"en": "Remove Company Logo", "ar": "إزالة شعار الشركة"},
    "data_folder": {"en": "Data folder", "ar": "مجلد البيانات"},
    "last_auto_backup": {"en": "Last auto-backup", "ar": "آخر نسخة احتياطية تلقائية"},
    "never_yet": {"en": "never yet", "ar": "لم يتم بعد"},
    "export_done": {"en": "Export finished.", "ar": "تم التصدير."},
    "close": {"en": "Close", "ar": "إغلاق"},
    "menu_reports": {"en": "&Reports", "ar": "&التقارير"},
    "menu_variance_report": {"en": "Variance report", "ar": "تقرير انحراف الحصر"},
    "var_title": {"en": "Variance report", "ar": "تقرير انحراف الحصر"},
    "var_group_by": {"en": "Group by:", "ar": "التجميع حسب:"},
    "var_group_area": {"en": "Area", "ar": "المنطقة"},
    "var_group_supplier": {"en": "Supplier", "ar": "المورّد"},
    "var_group_status": {"en": "Status", "ar": "الحالة"},
    "var_scope_label": {"en": "Scope", "ar": "النطاق"},
    "var_scope_project": {"en": "This project", "ar": "هذا المشروع"},
    "var_scope_all": {"en": "All projects", "ar": "كل المشاريع"},
    "var_empty": {"en": "No items to report.", "ar": "لا توجد بنود للتقرير."},
    "var_note": {"en": "Counts and percentages only — quantities are never summed, because one group can mix units (عدد / م.ط / مجموعة). Value is shown per currency.", "ar": "أعداد ونِسَب فقط — لا تُجمع الكميات لأن المجموعة قد تخلط وحدات مختلفة (عدد / م.ط / مجموعة). والقيمة معروضة لكل عملة على حدة."},
    "menu_open_logs": {"en": "Open log folder", "ar": "فتح مجلد السجلات"},
    "value_no_data": {"en": "No costs entered yet", "ar": "لم تُدخل تكاليف بعد"},
    "menu_toggle_tip": {"en": "Show / hide the menu", "ar": "إظهار / إخفاء القائمة"},
    "side_collapsed_tip": {"en": "Expand the menu (Ctrl+B)", "ar": "توسيع القائمة (Ctrl+B)"},
    "stat_projects": {"en": "Projects", "ar": "المشاريع"},
    "stat_value": {"en": "Purchasing value", "ar": "قيمة المشتريات"},
    "stat_pending": {"en": "Awaiting request", "ar": "بانتظار الطلب"},
    "stat_blocked": {"en": "On hold", "ar": "متوقف"},
    "stat_pending_sub": {"en": "no PR/PO yet", "ar": "بدون طلب / أمر شراء"},
    "stat_blocked_sub": {"en": "needs a decision", "ar": "يحتاج قرارًا"},
    "stat_items_unit": {"en": "items", "ar": "بند"},
    "side_section_nav": {"en": "Navigate", "ar": "التنقل"},
    "side_section_open": {"en": "Currently open", "ar": "مفتوحة الآن"},
    "side_section_tools": {"en": "Tools", "ar": "أدوات"},
    "search_all_projects": {"en": "Search all projects", "ar": "البحث في كل المشاريع"},
    "search_all_projects_tip": {"en": "Find an item by name across every project (Ctrl+Shift+F)", "ar": "ابحث عن بند بالاسم في كل المشاريع (Ctrl+Shift+F)"},
    "command_palette": {"en": "Command palette", "ar": "لوحة الأوامر"},
    "palette_placeholder": {"en": "Search projects, items, or run a command...", "ar": "ابحث عن مشروع أو بند، أو نفّذ أمرًا..."},
    "palette_group_projects": {"en": "PROJECTS", "ar": "المشاريع"},
    "palette_group_items": {"en": "ITEMS", "ar": "البنود"},
    "palette_group_actions": {"en": "ACTIONS", "ar": "أوامر"},
    "palette_no_results": {"en": "No matches", "ar": "لا توجد نتائج"},
    "palette_hint": {"en": "Up/Down to move · Enter to open · Esc to close", "ar": "أعلى/أسفل للتنقل · Enter للفتح · Esc للإغلاق"},
    "palette_action_add_item": {"en": "Add item", "ar": "إضافة بند"},
    "palette_action_export_pdf": {"en": "Export PDF report", "ar": "تصدير تقرير PDF"},
    "palette_action_search_all": {"en": "Search all projects", "ar": "البحث في كل المشاريع"},
    "palette_action_toggle_theme": {"en": "Switch light/dark mode", "ar": "تبديل الوضع الفاتح/الداكن"},
    "palette_action_toggle_language": {"en": "Switch language", "ar": "تبديل اللغة"},
}

_current_lang = "ar"


def set_language(lang):
    global _current_lang
    _current_lang = "ar" if lang == "ar" else "en"


def get_language():
    return _current_lang


def tr(key):
    entry = STRINGS.get(key)
    if not entry:
        return key
    return entry.get(_current_lang, entry.get("en", key))
