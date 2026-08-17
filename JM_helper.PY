import os
import re
import sys
import threading
import queue
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, StringVar, BooleanVar

# ===== 依赖检测 =====
PIL_OK = True
try:
    from PIL import Image
except Exception:
    PIL_OK = False

PDF_LIB = None
try:
    import pypdf
    PDF_LIB = 'pypdf'
except Exception:
    try:
        import PyPDF2 as pypdf
        PDF_LIB = 'PyPDF2'
    except Exception:
        PDF_LIB = None

DND_OK = True
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:
    DND_OK = False

# ===== 常量 =====
PDF_EXTS = {'.pdf'}
_FALLBACK_IMG_EXTS = {
    '.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.tiff', '.tif',
    '.ico', '.jfif', '.ppm', '.pgm', '.pbm', '.pnm', '.psd', '.tga',
    '.pcx', '.sgi', '.im', '.fli', '.flc', '.fpx', '.mic', '.mcidas',
    '.msp', '.pal', '.eps', '.xbm', '.xpm',
}

def _collect_img_exts():
    if PIL_OK:
        try:
            exts = set(Image.registered_extensions().keys())
            if exts:
                return exts - PDF_EXTS
        except Exception:
            pass
    return set(_FALLBACK_IMG_EXTS) - PDF_EXTS

IMG_EXTS = _collect_img_exts()

# ===== 漫画标签定义（标签名均为英文） =====
# 语言标签：常见语言 2-3 位英文简称
LANG_TAGS = [
    'CN', 'EN', 'ESP', 'JP', 'KO',
    'DE', 'FR', 'IT', 'PT', 'RU',
    'TH', 'VI', 'ID', 'AR', 'TR',
]
# 版式标签
FORMAT_TAGS = ['Vert', 'Horiz']
# 内容类型标签
CONTENT_TAGS = ['Photo']
# 内容分级标签（互斥）
RATING_TAGS = ['ALL', 'R18', 'R18G']

# 所有已知标签的集合（用于从文件名中清理旧标签）
_ALL_TAG_LITERALS = set(f'[{t}]' for t in LANG_TAGS + FORMAT_TAGS + CONTENT_TAGS + RATING_TAGS)

# 标签按钮颜色主题
TAG_THEME = {
    'lang':    {'bg': '#4a90d9', 'fg': '#ffffff', 'active': '#357abd', 'on_bg': '#2d5f9a'},
    'format':  {'bg': '#5cb85c', 'fg': '#ffffff', 'active': '#449d44', 'on_bg': '#2e6b2e'},
    'content': {'bg': '#f0ad4e', 'fg': '#ffffff', 'active': '#ec971f', 'on_bg': '#b06d1a'},
    'rating':  {'bg': '#d9534f', 'fg': '#ffffff', 'active': '#c9302c', 'on_bg': '#a02622'},
}

# 标签显示名的多语言翻译（按钮上显示用，文件名仍使用英文代码）
# 结构: {tag_code: {lang_code: display_name}}
TAG_I18N = {
    # 语言标签
    'CN':  {'zh_CN': '中文',     'zh_TW': '中文',     'en': 'Chinese'},
    'EN':  {'zh_CN': '英文',     'zh_TW': '英文',     'en': 'English'},
    'ESP': {'zh_CN': '西班牙文', 'zh_TW': '西班牙文', 'en': 'Spanish'},
    'JP':  {'zh_CN': '日文',     'zh_TW': '日文',     'en': 'Japanese'},
    'KO':  {'zh_CN': '韩文',     'zh_TW': '韓文',     'en': 'Korean'},
    'DE':  {'zh_CN': '德文',     'zh_TW': '德文',     'en': 'German'},
    'FR':  {'zh_CN': '法文',     'zh_TW': '法文',     'en': 'French'},
    'IT':  {'zh_CN': '意大利文', 'zh_TW': '義大利文', 'en': 'Italian'},
    'PT':  {'zh_CN': '葡萄牙文', 'zh_TW': '葡萄牙文', 'en': 'Portuguese'},
    'RU':  {'zh_CN': '俄文',     'zh_TW': '俄文',     'en': 'Russian'},
    'TH':  {'zh_CN': '泰文',     'zh_TW': '泰文',     'en': 'Thai'},
    'VI':  {'zh_CN': '越南文',   'zh_TW': '越南文',   'en': 'Vietnamese'},
    'ID':  {'zh_CN': '印尼文',   'zh_TW': '印尼文',   'en': 'Indonesian'},
    'AR':  {'zh_CN': '阿拉伯文', 'zh_TW': '阿拉伯文', 'en': 'Arabic'},
    'TR':  {'zh_CN': '土耳其文', 'zh_TW': '土耳其文', 'en': 'Turkish'},
    # 版式标签
    'Vert':  {'zh_CN': '窄版',    'zh_TW': '窄版',    'en': 'Vertical'},
    'Horiz': {'zh_CN': '宽版',    'zh_TW': '寬版',    'en': 'Horizontal'},
    # 内容标签
    'Photo': {'zh_CN': '写真',    'zh_TW': '寫真',    'en': 'Photo'},
    # 分级标签
    'ALL':  {'zh_CN': '全年龄',   'zh_TW': '全齡',    'en': 'All Ages'},
    'R18':  {'zh_CN': 'R18',      'zh_TW': 'R18',     'en': 'R18'},
    'R18G': {'zh_CN': 'R18G',     'zh_TW': 'R18G',    'en': 'R18G'},
}


def tag_display_name(tag_code: str, lang_code: str) -> str:
    """获取标签在指定界面语言下的显示名（带方括号）。
    文件名写入时仍使用英文代码 [EN]，按钮显示用 [英文]。"""
    translations = TAG_I18N.get(tag_code)
    if translations:
        name = translations.get(lang_code) or translations.get('en') or tag_code
        return f'[{name}]'
    return f'[{tag_code}]'

# ===== 多语言翻译表 =====
# 支持语言：简体中文(zh_CN)、繁体中文(zh_TW)、英文(en)
SUPPORTED_LANGS = ['zh_CN', 'zh_TW', 'en']
LANG_DISPLAY = {'zh_CN': '简体中文', 'zh_TW': '繁體中文', 'en': 'English'}

I18N = {
    'zh_CN': {
        'app_title': '漫画文件整理工具',
        'mode_label': '功能模式：',
        'mode_tagger': '漫画标签整理',
        'mode_img2pdf': '图片转 PDF',
        'mode_pdfmerge': 'PDF 合并',
        'clear_btn': '清空已选',
        'drop_hint': '将文件 / 文件夹 拖入此区域\n或点击下方按钮选择',
        'drop_title': '拖放文件或文件夹到此',
        'add_files': '添加文件...',
        'add_folder': '添加文件夹...',
        'output_settings': '输出设置',
        'output_name_label': '输出文件名：',
        'combine_chk': '将所有图片合成为一个 PDF（图片模式）',
        'delete_chk': '完成后删除源文件',
        'start_btn': '开始执行',
        'status_ready': '就绪',
        'status_renaming': '正在重命名...',
        'status_rename_done': '重命名完成',
        'status_added': '已添加 {added} 个文件（共 {total} 个）',
        'status_start_img2pdf': '开始执行：图片转 PDF',
        'status_start_pdfmerge': '开始执行：PDF 合并',
        'status_error': '出错',
        'col_original': '原文件名',
        'col_tags': '当前标签',
        'col_new_name': '新文件名预览',
        'tag_panel_title': '标签操作（先在上方列表选中文件，再点击标签按钮应用）',
        'lang_label': '语言：',
        'format_label': '版式：',
        'content_label': '内容：',
        'rating_label': '分级：',
        'btn_select_all': '全选',
        'btn_deselect_all': '取消全选',
        'btn_clear_tags': '清除选中文件标签',
        'btn_rename': '执行重命名',
        'no_tag': '—',
        'count_files': '{n} 个文件',
        'count_progress': '{done} / {total}',
        'warn_no_files': '未找到文件。',
        'warn_no_match_files': '未找到与当前模式匹配的文件。',
        'warn_no_selection': '请先在列表中选中文件。',
        'warn_no_rename': '没有需要重命名的文件。',
        'warn_conflict_title': '冲突警告',
        'warn_conflict_msg': '以下目标文件名已存在，继续可能导致覆盖或失败：\n{preview}{more}\n\n是否继续？',
        'warn_conflict_more': '\n...等共 {n} 个',
        'info_partial_fail_title': '部分失败',
        'info_partial_fail_msg': '重命名完成，{n} 个文件失败：\n{detail}{more}',
        'info_partial_fail_more': '\n...等共 {n} 个失败',
        'info_rename_success': '所有文件重命名成功！',
        'info_complete_title': '完成',
        'info_continue_title': '操作完成',
        'info_continue_msg': '操作已完成。是否继续进行其他文件处理？',
        'info_img2pdf_done': '图片转 PDF 完成！\n输出文件：{path}',
        'info_pdfmerge_done': 'PDF 合并完成！\n输出文件：{path}',
        'err_no_pillow': '未安装 Pillow：pip install pillow',
        'err_no_pypdf': '未安装 pypdf / PyPDF2',
        'err_title': '缺少依赖',
        'err_error_title': '错误',
        'deleted_source': '\n已删除源文件：{n} 个',
        'delete_failed': '\n删除失败：{n} 个\n{detail}',
        'status_processing_img': '处理图片：{name}',
        'status_merging': '合并：{name}',
        'hint_add_img': '请先添加图片文件。',
        'hint_add_pdf': '请先添加 PDF 文件。',
        'dnd_unavailable': '未检测到 tkinterdnd2，拖放不可用。\n请先安装：pip install tkinterdnd2\n或使用下方按钮添加。',
        'file_dialog_title': '选择文件',
        'folder_dialog_title': '选择文件夹',
        'ftype_all_img': '所有支持的图片',
        'ftype_manga': '漫画文件',
        'ftype_all': '所有文件',
        'default_output': '输出.pdf',
        'lang_menu': '语言',
    },
    'zh_TW': {
        'app_title': '漫畫檔案整理工具',
        'mode_label': '功能模式：',
        'mode_tagger': '漫畫標籤整理',
        'mode_img2pdf': '圖片轉 PDF',
        'mode_pdfmerge': 'PDF 合併',
        'clear_btn': '清空已選',
        'drop_hint': '將檔案 / 資料夾 拖入此區域\n或點擊下方按鈕選擇',
        'drop_title': '拖放檔案或資料夾到此',
        'add_files': '新增檔案...',
        'add_folder': '新增資料夾...',
        'output_settings': '輸出設定',
        'output_name_label': '輸出檔名：',
        'combine_chk': '將所有圖片合併為一個 PDF（圖片模式）',
        'delete_chk': '完成後刪除原始檔案',
        'start_btn': '開始執行',
        'status_ready': '就緒',
        'status_renaming': '正在重新命名...',
        'status_rename_done': '重新命名完成',
        'status_added': '已新增 {added} 個檔案（共 {total} 個）',
        'status_start_img2pdf': '開始執行：圖片轉 PDF',
        'status_start_pdfmerge': '開始執行：PDF 合併',
        'status_error': '錯誤',
        'col_original': '原始檔名',
        'col_tags': '目前標籤',
        'col_new_name': '新檔名預覽',
        'tag_panel_title': '標籤操作（先在上方清單選取檔案，再點擊標籤按鈕套用）',
        'lang_label': '語言：',
        'format_label': '版式：',
        'content_label': '內容：',
        'rating_label': '分級：',
        'btn_select_all': '全選',
        'btn_deselect_all': '取消全選',
        'btn_clear_tags': '清除選取檔案標籤',
        'btn_rename': '執行重新命名',
        'no_tag': '—',
        'count_files': '{n} 個檔案',
        'count_progress': '{done} / {total}',
        'warn_no_files': '未找到檔案。',
        'warn_no_match_files': '未找到與目前模式相符的檔案。',
        'warn_no_selection': '請先在清單中選取檔案。',
        'warn_no_rename': '沒有需要重新命名的檔案。',
        'warn_conflict_title': '衝突警告',
        'warn_conflict_msg': '以下目標檔名已存在，繼續可能導致覆寫或失敗：\n{preview}{more}\n\n是否繼續？',
        'warn_conflict_more': '\n...等共 {n} 個',
        'info_partial_fail_title': '部分失敗',
        'info_partial_fail_msg': '重新命名完成，{n} 個檔案失敗：\n{detail}{more}',
        'info_partial_fail_more': '\n...等共 {n} 個失敗',
        'info_rename_success': '所有檔案重新命名成功！',
        'info_complete_title': '完成',
        'info_continue_title': '操作完成',
        'info_continue_msg': '操作已完成。是否繼續進行其他檔案處理？',
        'info_img2pdf_done': '圖片轉 PDF 完成！\n輸出檔案：{path}',
        'info_pdfmerge_done': 'PDF 合併完成！\n輸出檔案：{path}',
        'err_no_pillow': '未安裝 Pillow：pip install pillow',
        'err_no_pypdf': '未安裝 pypdf / PyPDF2',
        'err_title': '缺少相依套件',
        'err_error_title': '錯誤',
        'deleted_source': '\n已刪除原始檔案：{n} 個',
        'delete_failed': '\n刪除失敗：{n} 個\n{detail}',
        'status_processing_img': '處理圖片：{name}',
        'status_merging': '合併：{name}',
        'hint_add_img': '請先新增圖片檔案。',
        'hint_add_pdf': '請先新增 PDF 檔案。',
        'dnd_unavailable': '未偵測到 tkinterdnd2，拖放不可用。\n請先安裝：pip install tkinterdnd2\n或使用下方按鈕新增。',
        'file_dialog_title': '選擇檔案',
        'folder_dialog_title': '選擇資料夾',
        'ftype_all_img': '所有支援的圖片',
        'ftype_manga': '漫畫檔案',
        'ftype_all': '所有檔案',
        'default_output': '輸出.pdf',
        'lang_menu': '語言',
    },
    'en': {
        'app_title': 'Manga File Organizer',
        'mode_label': 'Mode: ',
        'mode_tagger': 'Manga Tag Organizer',
        'mode_img2pdf': 'Images to PDF',
        'mode_pdfmerge': 'Merge PDFs',
        'clear_btn': 'Clear',
        'drop_hint': 'Drag files / folders here\nor click buttons below to select',
        'drop_title': 'Drop files or folders here',
        'add_files': 'Add Files...',
        'add_folder': 'Add Folder...',
        'output_settings': 'Output Settings',
        'output_name_label': 'Output filename: ',
        'combine_chk': 'Combine all images into one PDF (image mode)',
        'delete_chk': 'Delete source files after completion',
        'start_btn': 'Start',
        'status_ready': 'Ready',
        'status_renaming': 'Renaming...',
        'status_rename_done': 'Rename completed',
        'status_added': 'Added {added} file(s) ({total} total)',
        'status_start_img2pdf': 'Running: Images to PDF',
        'status_start_pdfmerge': 'Running: Merge PDFs',
        'status_error': 'Error',
        'col_original': 'Original Name',
        'col_tags': 'Current Tags',
        'col_new_name': 'New Name Preview',
        'tag_panel_title': 'Tag Actions (select files above, then click tag buttons to apply)',
        'lang_label': 'Lang: ',
        'format_label': 'Format: ',
        'content_label': 'Content: ',
        'rating_label': 'Rating: ',
        'btn_select_all': 'Select All',
        'btn_deselect_all': 'Deselect All',
        'btn_clear_tags': 'Clear Tags on Selected',
        'btn_rename': 'Execute Rename',
        'no_tag': '—',
        'count_files': '{n} file(s)',
        'count_progress': '{done} / {total}',
        'warn_no_files': 'No files found.',
        'warn_no_match_files': 'No files matching the current mode were found.',
        'warn_no_selection': 'Please select files in the list first.',
        'warn_no_rename': 'No files need renaming.',
        'warn_conflict_title': 'Conflict Warning',
        'warn_conflict_msg': 'The following target filenames already exist. Continuing may cause overwrite or failure:\n{preview}{more}\n\nContinue?',
        'warn_conflict_more': '\n...and {n} more',
        'info_partial_fail_title': 'Partial Failure',
        'info_partial_fail_msg': 'Rename completed, {n} file(s) failed:\n{detail}{more}',
        'info_partial_fail_more': '\n...and {n} more failures',
        'info_rename_success': 'All files renamed successfully!',
        'info_complete_title': 'Complete',
        'info_continue_title': 'Operation Complete',
        'info_continue_msg': 'Operation completed. Continue with other file processing?',
        'info_img2pdf_done': 'Images to PDF complete!\nOutput file: {path}',
        'info_pdfmerge_done': 'PDF merge complete!\nOutput file: {path}',
        'err_no_pillow': 'Pillow not installed: pip install pillow',
        'err_no_pypdf': 'pypdf / PyPDF2 not installed',
        'err_title': 'Missing Dependency',
        'err_error_title': 'Error',
        'deleted_source': '\nDeleted source files: {n}',
        'delete_failed': '\nDelete failed: {n}\n{detail}',
        'status_processing_img': 'Processing image: {name}',
        'status_merging': 'Merging: {name}',
        'hint_add_img': 'Please add image files first.',
        'hint_add_pdf': 'Please add PDF files first.',
        'dnd_unavailable': 'tkinterdnd2 not detected, drag-and-drop unavailable.\nInstall: pip install tkinterdnd2\nOr use buttons below to add.',
        'file_dialog_title': 'Select Files',
        'folder_dialog_title': 'Select Folder',
        'ftype_all_img': 'All supported images',
        'ftype_manga': 'Manga files',
        'ftype_all': 'All files',
        'default_output': 'output.pdf',
        'lang_menu': 'Language',
    },
}


class I18nManager:
    """简单国际化管理器，支持运行时切换语言。"""
    def __init__(self, lang_code='zh_CN'):
        self.lang_code = lang_code

    def set_lang(self, lang_code):
        if lang_code in SUPPORTED_LANGS:
            self.lang_code = lang_code

    def t(self, key, **kwargs):
        text = I18N.get(self.lang_code, I18N['en']).get(key, key)
        if kwargs:
            try:
                return text.format(**kwargs)
            except (KeyError, IndexError):
                return text
        return text


# ===== 工具函数 =====
def normalize_drop_paths(data: str):
    items = []
    token = ''
    in_brace = False
    for ch in data:
        if ch == '{':
            in_brace = True
            token = ''
        elif ch == '}':
            in_brace = False
            items.append(token)
            token = ''
        elif ch == ' ' and not in_brace:
            if token:
                items.append(token)
                token = ''
        else:
            token += ch
    if token:
        items.append(token)
    return [Path(p) for p in items]


def iter_files_from_paths(paths):
    """惰性遍历，避免一次性加载大量文件到内存。"""
    for p in paths:
        p = Path(p)
        if p.is_dir():
            for root, _, files in os.walk(p):
                for f in files:
                    yield Path(root) / f
        elif p.is_file():
            yield p


def is_image(p: Path):
    return p.suffix.lower() in IMG_EXTS


def is_pdf(p: Path):
    return p.suffix.lower() in PDF_EXTS


def strip_known_tags(name: str) -> str:
    """从文件名中移除所有已知标签，清理多余空格。"""
    result = name
    for tag in _ALL_TAG_LITERALS:
        result = result.replace(tag, '')
    result = re.sub(r'\s+', ' ', result).strip()
    return result if result else name


# ===== 文件项数据模型 =====
class FileItem:
    """表示一个待整理的漫画文件项，管理其标签状态和新文件名生成。"""

    __slots__ = ('path', 'suffix', 'base_name', 'format_tag', 'lang_tag',
                 'content_tags', 'rating_tag')

    def __init__(self, path: Path):
        self.path = path
        self.suffix = path.suffix
        self.base_name = strip_known_tags(path.stem)
        self.format_tag = None    # 'Vert' | 'Horiz' | None
        self.lang_tag = None      # 'CN' | 'EN' | ... | None
        self.content_tags = set() # subset of CONTENT_TAGS
        self.rating_tag = None    # 'ALL' | 'R18' | 'R18G' | None

    def get_new_name(self) -> str:
        """生成新的完整文件名（含扩展名），标签顺序：版式 → 语言 → 内容 → 分级。"""
        parts = [self.base_name]
        if self.format_tag:
            parts.append(f'[{self.format_tag}]')
        if self.lang_tag:
            parts.append(f'[{self.lang_tag}]')
        for tag in CONTENT_TAGS:
            if tag in self.content_tags:
                parts.append(f'[{tag}]')
        if self.rating_tag:
            parts.append(f'[{self.rating_tag}]')
        return ' '.join(parts) + self.suffix

    @property
    def needs_rename(self) -> bool:
        return self.path.name != self.get_new_name()

    def get_tag_display(self) -> str:
        tags = []
        if self.format_tag:
            tags.append(f'[{self.format_tag}]')
        if self.lang_tag:
            tags.append(f'[{self.lang_tag}]')
        for tag in CONTENT_TAGS:
            if tag in self.content_tags:
                tags.append(f'[{tag}]')
        if self.rating_tag:
            tags.append(f'[{self.rating_tag}]')
        return ' '.join(tags) if tags else None


# ===== 主应用 =====
class App:
    def __init__(self, root):
        self.root = root
        self.i18n = I18nManager('zh_CN')

        self.root.title(self.i18n.t('app_title'))
        self.root.geometry("1020x760")
        self.root.minsize(900, 640)

        # 模式
        self.mode = StringVar(value='tagger')

        # 通用状态
        self.output_name = StringVar(value=self.i18n.t('default_output'))
        self.combine_images = BooleanVar(value=True)
        self.delete_source = BooleanVar(value=False)
        self.status_var = StringVar(value=self.i18n.t('status_ready'))
        self.count_var = StringVar(value='0 / 0')

        # 标签整理专用
        self.file_items = []

        # 图片转PDF / PDF合并专用
        self.selected_files = []

        self.ui_queue = queue.Queue()

        self._build_ui()
        self._setup_dnd()
        self._poll_ui_queue()
        self._apply_language()

    def _tr(self, key, **kwargs):
        return self.i18n.t(key, **kwargs)

    def _tag_display(self, tag_code: str) -> str:
        """获取标签在当前界面语言下的显示名（带方括号）。"""
        return tag_display_name(tag_code, self.i18n.lang_code)

    # ---------- UI 构建 ----------
    def _build_ui(self):
        # 顶部：模式选择 + 语言切换
        top = ttk.Frame(self.root, padding=(10, 10))
        top.pack(fill=tk.X)
        ttk.Label(top, textvariable=tk.StringVar()).pack(side=tk.LEFT)  # 占位
        self.mode_label = ttk.Label(top, text=self._tr('mode_label'))
        self.mode_label.pack(side=tk.LEFT)
        self.rb_tagger = ttk.Radiobutton(top, text=self._tr('mode_tagger'), value='tagger',
                                         variable=self.mode, command=self.on_mode_change)
        self.rb_tagger.pack(side=tk.LEFT, padx=5)
        self.rb_img2pdf = ttk.Radiobutton(top, text=self._tr('mode_img2pdf'), value='img2pdf',
                                          variable=self.mode, command=self.on_mode_change)
        self.rb_img2pdf.pack(side=tk.LEFT, padx=5)
        self.rb_pdfmerge = ttk.Radiobutton(top, text=self._tr('mode_pdfmerge'), value='pdfmerge',
                                           variable=self.mode, command=self.on_mode_change)
        self.rb_pdfmerge.pack(side=tk.LEFT, padx=5)
        self.clear_btn = ttk.Button(top, text=self._tr('clear_btn'), command=self.clear_files)
        self.clear_btn.pack(side=tk.LEFT, padx=15)

        # 语言选择下拉
        ttk.Label(top, text=self._tr('lang_menu') + '：').pack(side=tk.RIGHT)
        self.lang_var = StringVar(value=self.i18n.lang_code)
        self.lang_combo = ttk.Combobox(top, textvariable=self.lang_var,
                                       values=[f"{LANG_DISPLAY[l]} ({l})" for l in SUPPORTED_LANGS],
                                       state='readonly', width=14)
        # 设置初始显示
        self.lang_combo.set(f"{LANG_DISPLAY[self.i18n.lang_code]} ({self.i18n.lang_code})")
        self.lang_combo.pack(side=tk.RIGHT, padx=(5, 0))
        self.lang_combo.bind('<<ComboboxSelected>>', self._on_lang_change)

        # 拖放区域
        self.mid = ttk.LabelFrame(self.root, text=self._tr('drop_title'), padding=(8, 8))
        self.mid.pack(fill=tk.X, padx=10, pady=10)
        self.drop_area = tk.Label(self.mid, text=self._tr('drop_hint'),
                                  relief=tk.RIDGE, bd=2, fg="#555", height=3)
        self.drop_area.pack(fill=tk.X, expand=False, pady=(0, 5))

        # 添加按钮
        btns = ttk.Frame(self.root)
        btns.pack(fill=tk.X, padx=10)
        self.add_files_btn = ttk.Button(btns, text=self._tr('add_files'), command=self.choose_files)
        self.add_files_btn.pack(side=tk.LEFT)
        self.add_folder_btn = ttk.Button(btns, text=self._tr('add_folder'), command=self.choose_folder)
        self.add_folder_btn.pack(side=tk.LEFT, padx=5)

        # 文件列表容器
        self.list_container = ttk.Frame(self.root)
        self.list_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self._build_tagger_ui()
        self._build_simple_list_ui()

        # 输出设置
        self.out_frame = ttk.LabelFrame(self.root, text=self._tr('output_settings'), padding=(8, 8))
        self.out_frame.pack(fill=tk.X, padx=10, pady=(10, 5))
        row1 = ttk.Frame(self.out_frame)
        row1.pack(fill=tk.X, pady=(0, 5))
        self.out_name_label = ttk.Label(row1, text=self._tr('output_name_label'))
        self.out_name_label.pack(side=tk.LEFT)
        self.out_entry = ttk.Entry(row1, textvariable=self.output_name, width=30)
        self.out_entry.pack(side=tk.LEFT, padx=(5, 15))
        self.combine_chk = ttk.Checkbutton(row1, text=self._tr('combine_chk'),
                                           variable=self.combine_images)
        self.combine_chk.pack(side=tk.LEFT)
        self.delete_chk = ttk.Checkbutton(row1, text=self._tr('delete_chk'),
                                          variable=self.delete_source)
        self.delete_chk.pack(side=tk.LEFT, padx=(15, 0))

        # 进度条
        barf = ttk.Frame(self.root, padding=(10, 0))
        barf.pack(fill=tk.X)
        self.progress = ttk.Progressbar(barf, orient=tk.HORIZONTAL, length=400, mode='determinate')
        self.progress.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(barf, textvariable=self.count_var, width=10).pack(side=tk.LEFT)
        ttk.Label(barf, textvariable=self.status_var).pack(side=tk.LEFT, padx=(10, 0))

        # 底部按钮
        bottom = ttk.Frame(self.root, padding=(10, 10))
        bottom.pack(fill=tk.X)
        self.start_btn = ttk.Button(bottom, text=self._tr('start_btn'), command=self.start)
        self.start_btn.pack(side=tk.RIGHT)

        self._update_mode_ui()

    def _build_tagger_ui(self):
        """构建标签整理模式的 UI：Treeview 多选列表 + 游戏化标签按钮。"""
        self.tagger_frame = ttk.Frame(self.list_container)

        # 文件列表
        tree_frame = ttk.Frame(self.tagger_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(tree_frame, columns=('original', 'tags', 'new_name'),
                                 show='headings', selectmode='extended')
        self.tree.heading('original', text=self._tr('col_original'))
        self.tree.heading('tags', text=self._tr('col_tags'))
        self.tree.heading('new_name', text=self._tr('col_new_name'))
        self.tree.column('original', width=280, minwidth=150)
        self.tree.column('tags', width=140, minwidth=80)
        self.tree.column('new_name', width=340, minwidth=200)

        tree_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)

        # 标签操作面板
        self.tag_panel = ttk.LabelFrame(self.tagger_frame,
                                        text=self._tr('tag_panel_title'),
                                        padding=(10, 8))
        self.tag_panel.pack(fill=tk.X, pady=(8, 0))

        # 语言标签行
        self.lang_row = ttk.Frame(self.tag_panel)
        self.lang_row.pack(fill=tk.X, pady=3)
        self.lang_label = ttk.Label(self.lang_row, text=self._tr('lang_label'), width=8)
        self.lang_label.pack(side=tk.LEFT)
        self.lang_buttons = {}
        for tag in LANG_TAGS:
            btn = tk.Button(self.lang_row, text=f'[{tag}]',
                            bg=TAG_THEME['lang']['bg'], fg=TAG_THEME['lang']['fg'],
                            activebackground=TAG_THEME['lang']['active'],
                            activeforeground=TAG_THEME['lang']['fg'],
                            relief=tk.RAISED, bd=2, padx=10, pady=3, cursor='hand2',
                            font=('Segoe UI', 9, 'bold'),
                            command=lambda t=tag: self.toggle_lang_tag(t))
            btn.pack(side=tk.LEFT, padx=3)
            self.lang_buttons[tag] = btn

        # 版式标签行
        self.fmt_row = ttk.Frame(self.tag_panel)
        self.fmt_row.pack(fill=tk.X, pady=3)
        self.fmt_label = ttk.Label(self.fmt_row, text=self._tr('format_label'), width=8)
        self.fmt_label.pack(side=tk.LEFT)
        self.format_buttons = {}
        for tag in FORMAT_TAGS:
            btn = tk.Button(self.fmt_row, text=f'[{tag}]',
                            bg=TAG_THEME['format']['bg'], fg=TAG_THEME['format']['fg'],
                            activebackground=TAG_THEME['format']['active'],
                            activeforeground=TAG_THEME['format']['fg'],
                            relief=tk.RAISED, bd=2, padx=12, pady=3, cursor='hand2',
                            font=('Segoe UI', 10, 'bold'),
                            command=lambda t=tag: self.toggle_format_tag(t))
            btn.pack(side=tk.LEFT, padx=4)
            self.format_buttons[tag] = btn

        # 内容标签行
        self.content_row = ttk.Frame(self.tag_panel)
        self.content_row.pack(fill=tk.X, pady=3)
        self.content_label = ttk.Label(self.content_row, text=self._tr('content_label'), width=8)
        self.content_label.pack(side=tk.LEFT)
        self.content_buttons = {}
        for tag in CONTENT_TAGS:
            btn = tk.Button(self.content_row, text=f'[{tag}]',
                            bg=TAG_THEME['content']['bg'], fg=TAG_THEME['content']['fg'],
                            activebackground=TAG_THEME['content']['active'],
                            activeforeground=TAG_THEME['content']['fg'],
                            relief=tk.RAISED, bd=2, padx=12, pady=3, cursor='hand2',
                            font=('Segoe UI', 10, 'bold'),
                            command=lambda t=tag: self.toggle_content_tag(t))
            btn.pack(side=tk.LEFT, padx=4)
            self.content_buttons[tag] = btn

        # 分级标签行
        self.rating_row = ttk.Frame(self.tag_panel)
        self.rating_row.pack(fill=tk.X, pady=3)
        self.rating_label = ttk.Label(self.rating_row, text=self._tr('rating_label'), width=8)
        self.rating_label.pack(side=tk.LEFT)
        self.rating_buttons = {}
        for tag in RATING_TAGS:
            btn = tk.Button(self.rating_row, text=f'[{tag}]',
                            bg=TAG_THEME['rating']['bg'], fg=TAG_THEME['rating']['fg'],
                            activebackground=TAG_THEME['rating']['active'],
                            activeforeground=TAG_THEME['rating']['fg'],
                            relief=tk.RAISED, bd=2, padx=12, pady=3, cursor='hand2',
                            font=('Segoe UI', 10, 'bold'),
                            command=lambda t=tag: self.toggle_rating_tag(t))
            btn.pack(side=tk.LEFT, padx=4)
            self.rating_buttons[tag] = btn

        # 操作按钮行
        op_row = ttk.Frame(self.tag_panel)
        op_row.pack(fill=tk.X, pady=(8, 0))
        self.btn_select_all = ttk.Button(op_row, text=self._tr('btn_select_all'), command=self.select_all)
        self.btn_select_all.pack(side=tk.LEFT, padx=3)
        self.btn_deselect_all = ttk.Button(op_row, text=self._tr('btn_deselect_all'), command=self.deselect_all)
        self.btn_deselect_all.pack(side=tk.LEFT, padx=3)
        self.btn_clear_tags = ttk.Button(op_row, text=self._tr('btn_clear_tags'), command=self.clear_tags_selected)
        self.btn_clear_tags.pack(side=tk.LEFT, padx=3)
        self.btn_rename = ttk.Button(op_row, text=self._tr('btn_rename'), command=self.execute_rename)
        self.btn_rename.pack(side=tk.RIGHT, padx=3)

    def _build_simple_list_ui(self):
        """构建图片转PDF / PDF合并模式的简单滚动列表。"""
        self.simple_frame = ttk.Frame(self.list_container)

        self.canvas = tk.Canvas(self.simple_frame)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vbar = ttk.Scrollbar(self.simple_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        vbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.configure(yscrollcommand=vbar.set)
        self.names_frame = ttk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.names_frame, anchor='nw')

        def _on_mousewheel(event):
            delta = event.delta
            if sys.platform == 'darwin':
                delta = event.delta
            elif event.num == 5:
                delta = -120
            elif event.num == 4:
                delta = 120
            self.canvas.yview_scroll(int(-1 * (delta / 120)), "units")

        self.canvas.bind("<MouseWheel>", _on_mousewheel)
        self.canvas.bind("<Button-4>", _on_mousewheel)
        self.canvas.bind("<Button-5>", _on_mousewheel)
        self.names_frame.bind("<Configure>",
                              lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

    def _update_mode_ui(self):
        """根据当前模式切换 UI 显示。"""
        mode = self.mode.get()
        if mode == 'tagger':
            self.simple_frame.pack_forget()
            self.tagger_frame.pack(fill=tk.BOTH, expand=True)
            self.out_frame.pack_forget()
            self.start_btn.pack_forget()
        else:
            self.tagger_frame.pack_forget()
            self.simple_frame.pack(fill=tk.BOTH, expand=True)
            self.out_frame.pack(fill=tk.X, padx=10, pady=(10, 5))
            self.start_btn.pack(side=tk.RIGHT)

    # ---------- 语言切换 ----------
    def _on_lang_change(self, event=None):
        """处理语言切换。"""
        selection = self.lang_var.get()
        # 从 "简体中文 (zh_CN)" 格式中提取语言代码
        for lang in SUPPORTED_LANGS:
            if lang in selection:
                self.i18n.set_lang(lang)
                break
        self._apply_language()

    def _apply_language(self):
        """应用当前语言到所有 UI 文本。"""
        self.root.title(self._tr('app_title'))
        self.mode_label.config(text=self._tr('mode_label'))
        self.rb_tagger.config(text=self._tr('mode_tagger'))
        self.rb_img2pdf.config(text=self._tr('mode_img2pdf'))
        self.rb_pdfmerge.config(text=self._tr('mode_pdfmerge'))
        self.clear_btn.config(text=self._tr('clear_btn'))
        self.mid.config(text=self._tr('drop_title'))
        self.drop_area.config(text=self._tr('drop_hint'))
        self.add_files_btn.config(text=self._tr('add_files'))
        self.add_folder_btn.config(text=self._tr('add_folder'))
        self.out_frame.config(text=self._tr('output_settings'))
        self.out_name_label.config(text=self._tr('output_name_label'))
        self.combine_chk.config(text=self._tr('combine_chk'))
        self.delete_chk.config(text=self._tr('delete_chk'))
        self.start_btn.config(text=self._tr('start_btn'))
        # 标签面板
        self.tag_panel.config(text=self._tr('tag_panel_title'))
        self.lang_label.config(text=self._tr('lang_label'))
        self.fmt_label.config(text=self._tr('format_label'))
        self.content_label.config(text=self._tr('content_label'))
        self.rating_label.config(text=self._tr('rating_label'))
        self.btn_select_all.config(text=self._tr('btn_select_all'))
        self.btn_deselect_all.config(text=self._tr('btn_deselect_all'))
        self.btn_clear_tags.config(text=self._tr('btn_clear_tags'))
        self.btn_rename.config(text=self._tr('btn_rename'))
        # Treeview 表头
        self.tree.heading('original', text=self._tr('col_original'))
        self.tree.heading('tags', text=self._tr('col_tags'))
        self.tree.heading('new_name', text=self._tr('col_new_name'))
        # 标签按钮显示文本（本地化翻译，文件名仍用英文代码）
        for tag, btn in self.lang_buttons.items():
            btn.config(text=self._tag_display(tag))
        for tag, btn in self.format_buttons.items():
            btn.config(text=self._tag_display(tag))
        for tag, btn in self.content_buttons.items():
            btn.config(text=self._tag_display(tag))
        for tag, btn in self.rating_buttons.items():
            btn.config(text=self._tag_display(tag))
        # 状态
        if self.status_var.get() == '就绪' or self.status_var.get() == 'Ready' or self.status_var.get() == '就緒':
            self.status_var.set(self._tr('status_ready'))
        # 刷新列表显示
        self.refresh_tree()
        self._update_tag_button_states()

    # ---------- DND ----------
    def _setup_dnd(self):
        if DND_OK and isinstance(self.root, TkinterDnD.Tk):
            self.drop_area.drop_target_register(DND_FILES)
            self.drop_area.dnd_bind("<<Drop>>", self.on_drop)
        else:
            self.drop_area.config(text=self._tr('dnd_unavailable'))

    # ---------- 通用文件操作 ----------
    def on_mode_change(self):
        self._update_mode_ui()
        self.clear_files()

    def clear_files(self):
        self.file_items.clear()
        self.selected_files.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)
        for w in self.names_frame.winfo_children():
            w.destroy()
        self.progress['value'] = 0
        self.status_var.set(self._tr('status_ready'))
        self.count_var.set('0 / 0')
        self._update_tag_button_states()

    def on_drop(self, event):
        paths = normalize_drop_paths(event.data)
        self.add_paths(paths)

    def choose_files(self):
        mode = self.mode.get()
        if mode == 'img2pdf':
            ext_patterns = " ".join(f"*{e}" for e in sorted(IMG_EXTS))
            types = [
                (self._tr('ftype_all_img'), ext_patterns),
                ("PNG", "*.png"),
                ("JPEG", "*.jpg *.jpeg *.jfif"),
                ("WebP", "*.webp"),
                ("GIF", "*.gif"),
                ("BMP", "*.bmp"),
                ("TIFF", "*.tif *.tiff"),
                (self._tr('ftype_all'), "*.*"),
            ]
        elif mode == 'pdfmerge':
            types = [("PDF", "*.pdf")]
        else:
            types = [
                (self._tr('ftype_manga'), "*.pdf *.cbz *.cbr *.cb7 *.cbt *.epub *.zip *.rar *.7z"),
                ("PDF", "*.pdf"),
                (self._tr('ftype_all'), "*.*"),
            ]
        files = filedialog.askopenfilenames(title=self._tr('file_dialog_title'), filetypes=types)
        if files:
            self.add_paths([Path(f) for f in files])

    def choose_folder(self):
        folder = filedialog.askdirectory(title=self._tr('folder_dialog_title'))
        if folder:
            self.add_paths([Path(folder)])

    def add_paths(self, paths):
        mode = self.mode.get()
        if mode == 'tagger':
            new_files = list(iter_files_from_paths(paths))
            if not new_files:
                messagebox.showwarning(self._tr('info_complete_title'), self._tr('warn_no_files'))
                return
            existing = {str(item.path.resolve()) for item in self.file_items}
            added = 0
            for f in new_files:
                rp = str(f.resolve())
                if rp not in existing:
                    self.file_items.append(FileItem(f))
                    existing.add(rp)
                    added += 1
            if added:
                self.refresh_tree()
                self.status_var.set(self._tr('status_added', added=added, total=len(self.file_items)))
        else:
            new_files = []
            for f in iter_files_from_paths(paths):
                if mode == 'img2pdf' and is_image(f):
                    new_files.append(f)
                elif mode == 'pdfmerge' and is_pdf(f):
                    new_files.append(f)
            if not new_files:
                messagebox.showwarning(self._tr('info_complete_title'), self._tr('warn_no_match_files'))
                return
            existing = set(map(lambda p: str(p.resolve()), self.selected_files))
            for f in new_files:
                rp = str(f.resolve())
                if rp not in existing:
                    self.selected_files.append(f)
                    existing.add(rp)
            self.refresh_name_chips()

    # ---------- 标签整理：Treeview ----------
    def refresh_tree(self):
        """刷新 Treeview 显示。"""
        self.tree.delete(*self.tree.get_children())
        for idx, item in enumerate(self.file_items, start=1):
            self.tree.insert('', tk.END, iid=str(idx - 1),
                             values=(item.path.name,
                                     item.get_tag_display() or self._tr('no_tag'),
                                     item.get_new_name()))
        self.count_var.set(self._tr('count_files', n=len(self.file_items)))

    def _get_selected_indices(self):
        return [int(s) for s in self.tree.selection()]

    def _on_tree_select(self, event=None):
        self._update_tag_button_states()

    def _update_tag_button_states(self):
        """根据选中文件的标签状态，更新标签按钮的视觉反馈。"""
        indices = self._get_selected_indices()
        if not indices:
            for btn in self.lang_buttons.values():
                btn.config(relief=tk.RAISED, bg=TAG_THEME['lang']['bg'])
            for btn in self.format_buttons.values():
                btn.config(relief=tk.RAISED, bg=TAG_THEME['format']['bg'])
            for btn in self.content_buttons.values():
                btn.config(relief=tk.RAISED, bg=TAG_THEME['content']['bg'])
            for btn in self.rating_buttons.values():
                btn.config(relief=tk.RAISED, bg=TAG_THEME['rating']['bg'])
            return

        selected_items = [self.file_items[i] for i in indices]

        for tag in LANG_TAGS:
            btn = self.lang_buttons[tag]
            all_have = all(item.lang_tag == tag for item in selected_items)
            if all_have:
                btn.config(relief=tk.SUNKEN, bg=TAG_THEME['lang']['on_bg'])
            else:
                btn.config(relief=tk.RAISED, bg=TAG_THEME['lang']['bg'])

        for tag in FORMAT_TAGS:
            btn = self.format_buttons[tag]
            all_have = all(item.format_tag == tag for item in selected_items)
            if all_have:
                btn.config(relief=tk.SUNKEN, bg=TAG_THEME['format']['on_bg'])
            else:
                btn.config(relief=tk.RAISED, bg=TAG_THEME['format']['bg'])

        for tag in CONTENT_TAGS:
            btn = self.content_buttons[tag]
            all_have = all(tag in item.content_tags for item in selected_items)
            if all_have:
                btn.config(relief=tk.SUNKEN, bg=TAG_THEME['content']['on_bg'])
            else:
                btn.config(relief=tk.RAISED, bg=TAG_THEME['content']['bg'])

        for tag in RATING_TAGS:
            btn = self.rating_buttons[tag]
            all_have = all(item.rating_tag == tag for item in selected_items)
            if all_have:
                btn.config(relief=tk.SUNKEN, bg=TAG_THEME['rating']['on_bg'])
            else:
                btn.config(relief=tk.RAISED, bg=TAG_THEME['rating']['bg'])

    # ---------- 标签操作 ----------
    def toggle_lang_tag(self, tag: str):
        indices = self._get_selected_indices()
        if not indices:
            messagebox.showinfo(self._tr('info_complete_title'), self._tr('warn_no_selection'))
            return
        selected_items = [self.file_items[i] for i in indices]
        all_have = all(item.lang_tag == tag for item in selected_items)
        for item in selected_items:
            item.lang_tag = None if all_have else tag
        self._refresh_selected_rows(indices)
        self._update_tag_button_states()

    def toggle_format_tag(self, tag: str):
        indices = self._get_selected_indices()
        if not indices:
            messagebox.showinfo(self._tr('info_complete_title'), self._tr('warn_no_selection'))
            return
        selected_items = [self.file_items[i] for i in indices]
        all_have = all(item.format_tag == tag for item in selected_items)
        for item in selected_items:
            item.format_tag = None if all_have else tag
        self._refresh_selected_rows(indices)
        self._update_tag_button_states()

    def toggle_content_tag(self, tag: str):
        indices = self._get_selected_indices()
        if not indices:
            messagebox.showinfo(self._tr('info_complete_title'), self._tr('warn_no_selection'))
            return
        selected_items = [self.file_items[i] for i in indices]
        all_have = all(tag in item.content_tags for item in selected_items)
        for item in selected_items:
            if all_have:
                item.content_tags.discard(tag)
            else:
                item.content_tags.add(tag)
        self._refresh_selected_rows(indices)
        self._update_tag_button_states()

    def toggle_rating_tag(self, tag: str):
        """切换分级标签：互斥，点击相同标签则取消。"""
        indices = self._get_selected_indices()
        if not indices:
            messagebox.showinfo(self._tr('info_complete_title'), self._tr('warn_no_selection'))
            return
        selected_items = [self.file_items[i] for i in indices]
        all_have = all(item.rating_tag == tag for item in selected_items)
        for item in selected_items:
            item.rating_tag = None if all_have else tag
        self._refresh_selected_rows(indices)
        self._update_tag_button_states()

    def clear_tags_selected(self):
        indices = self._get_selected_indices()
        if not indices:
            messagebox.showinfo(self._tr('info_complete_title'), self._tr('warn_no_selection'))
            return
        for i in indices:
            item = self.file_items[i]
            item.format_tag = None
            item.lang_tag = None
            item.content_tags.clear()
            item.rating_tag = None
        self._refresh_selected_rows(indices)
        self._update_tag_button_states()

    def _refresh_selected_rows(self, indices):
        for i in indices:
            item = self.file_items[i]
            self.tree.item(str(i), values=(item.path.name,
                                           item.get_tag_display() or self._tr('no_tag'),
                                           item.get_new_name()))

    def select_all(self):
        all_ids = self.tree.get_children()
        if all_ids:
            self.tree.selection_set(all_ids)
        self._update_tag_button_states()

    def deselect_all(self):
        self.tree.selection_remove(self.tree.selection())
        self._update_tag_button_states()

    # ---------- 多核并行重命名 ----------
    def execute_rename(self):
        items_to_rename = [item for item in self.file_items if item.needs_rename]
        if not items_to_rename:
            messagebox.showinfo(self._tr('info_complete_title'), self._tr('warn_no_rename'))
            return

        conflicts = []
        for item in items_to_rename:
            new_path = item.path.parent / item.get_new_name()
            if new_path.exists() and new_path.resolve() != item.path.resolve():
                conflicts.append(item.get_new_name())
        if conflicts:
            preview = '\n'.join(conflicts[:5])
            more = self._tr('warn_conflict_more', n=len(conflicts)) if len(conflicts) > 5 else ''
            if not messagebox.askyesno(self._tr('warn_conflict_title'),
                    self._tr('warn_conflict_msg', preview=preview, more=more)):
                return

        total = len(items_to_rename)
        self.progress['maximum'] = total
        self.progress['value'] = 0
        self.count_var.set(self._tr('count_progress', done=0, total=total))
        self.status_var.set(self._tr('status_renaming'))
        self.start_btn.config(state=tk.DISABLED)

        max_workers = min(os.cpu_count() or 4, 8)

        def do_rename():
            processed = [0]
            failed = []
            lock = threading.Lock()

            def rename_one(item):
                try:
                    new_path = item.path.parent / item.get_new_name()
                    if new_path.resolve() == item.path.resolve():
                        return True, None
                    item.path.rename(new_path)
                    item.path = new_path
                    return True, None
                except Exception as e:
                    return False, str(e)

            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                future_map = {pool.submit(rename_one, item): item for item in items_to_rename}
                for future in as_completed(future_map):
                    item = future_map[future]
                    success, error = future.result()
                    if not success:
                        failed.append((item.path.name, error))
                    with lock:
                        processed[0] += 1
                        self.ui_queue.put(('progress', (processed[0], total)))

            self.ui_queue.put(('rename_done', failed))

        t = threading.Thread(target=do_rename, daemon=True)
        t.start()

    # ---------- 图片转PDF / PDF合并 ----------
    def refresh_name_chips(self):
        for w in self.names_frame.winfo_children():
            w.destroy()
        for idx, p in enumerate(self.selected_files, start=1):
            chip = ttk.Label(self.names_frame, text=f"{idx}. {p.name}", relief=tk.GROOVE, padding=(6, 3))
            chip.pack(fill=tk.X, padx=2, pady=2)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.count_var.set(self._tr('count_files', n=len(self.selected_files)))

    def start(self):
        mode = self.mode.get()
        if mode == 'img2pdf':
            self._start_img2pdf()
        elif mode == 'pdfmerge':
            self._start_pdfmerge()

    def _start_img2pdf(self):
        if not PIL_OK:
            messagebox.showerror(self._tr('err_title'), self._tr('err_no_pillow'))
            return
        if not self.selected_files:
            messagebox.showwarning(self._tr('info_complete_title'), self._tr('hint_add_img'))
            return
        name = self.output_name.get().strip() or self._tr('default_output')
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        self.status_var.set(self._tr('status_start_img2pdf'))
        self.progress['value'] = 0
        self.count_var.set(self._tr('count_progress', done=0, total=len(self.selected_files)))
        self._run_in_thread(self.run_img2pdf, name)

    def _start_pdfmerge(self):
        if PDF_LIB is None:
            messagebox.showerror(self._tr('err_title'), self._tr('err_no_pypdf'))
            return
        if not self.selected_files:
            messagebox.showwarning(self._tr('info_complete_title'), self._tr('hint_add_pdf'))
            return
        name = self.output_name.get().strip() or self._tr('default_output')
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        self.status_var.set(self._tr('status_start_pdfmerge'))
        self.progress['value'] = 0
        self.count_var.set(self._tr('count_progress', done=0, total=len(self.selected_files)))
        self._run_in_thread(self.run_pdfmerge, name)

    def _run_in_thread(self, func, *args):
        self.start_btn.config(state=tk.DISABLED)
        t = threading.Thread(target=self._thread_wrapper, args=(func, *args), daemon=True)
        t.start()

    def _thread_wrapper(self, func, *args):
        try:
            func(*args)
        except Exception as e:
            self.ui_queue.put(('error', str(e)))
        finally:
            self.ui_queue.put(('done', None))

    # ---------- UI 队列轮询 ----------
    def _poll_ui_queue(self):
        try:
            while True:
                kind, payload = self.ui_queue.get_nowait()
                if kind == 'progress':
                    processed, total = payload
                    self.progress['maximum'] = max(1, total)
                    self.progress['value'] = processed
                    self.count_var.set(self._tr('count_progress', done=processed, total=total))
                elif kind == 'status':
                    self.status_var.set(payload)
                elif kind == 'error':
                    messagebox.showerror(self._tr('err_error_title'), payload)
                    self.status_var.set(self._tr('status_error'))
                elif kind == 'info':
                    messagebox.showinfo(self._tr('info_complete_title'), payload)
                elif kind == 'rename_done':
                    failed = payload
                    self.refresh_tree()
                    self.start_btn.config(state=tk.NORMAL)
                    if failed:
                        detail = '\n'.join(f"{name}：{err}" for name, err in failed[:10])
                        more = self._tr('info_partial_fail_more', n=len(failed)) if len(failed) > 10 else ''
                        messagebox.showwarning(self._tr('info_partial_fail_title'),
                            self._tr('info_partial_fail_msg', n=len(failed), detail=detail, more=more))
                    else:
                        messagebox.showinfo(self._tr('info_complete_title'), self._tr('info_rename_success'))
                    self.status_var.set(self._tr('status_rename_done'))
                elif kind == 'done':
                    self.start_btn.config(state=tk.NORMAL)
                    self.ask_continue_or_exit()
        except queue.Empty:
            pass
        self.root.after(80, self._poll_ui_queue)

    def ask_continue_or_exit(self):
        cont = messagebox.askyesno(self._tr('info_continue_title'), self._tr('info_continue_msg'))
        if not cont:
            self.root.destroy()
        else:
            self.clear_files()
            self.status_var.set(self._tr('status_ready'))

    # ---------- 图片转 PDF ----------
    def run_img2pdf(self, output_name):
        imgs = self.selected_files
        total = len(imgs)
        out_dir = imgs[0].parent.parent
        out_path = out_dir / output_name
        pil_images = []
        processed = 0
        for p in imgs:
            self.ui_queue.put(('status', self._tr('status_processing_img', name=p.name)))
            with Image.open(p) as im:
                im = im.convert('RGB')
                pil_images.append(im.copy())
            processed += 1
            self.ui_queue.put(('progress', (processed, total)))

        if self.combine_images.get():
            first = pil_images[0]
            rest = pil_images[1:]
            first.save(out_path, "PDF", save_all=True, append_images=rest)
            outputs = [out_path]
        else:
            outputs = []
            out_stem = Path(output_name).stem
            for idx, im in enumerate(pil_images, start=1):
                single_name = out_dir / f"{out_stem}_{idx}.pdf"
                im.save(single_name, "PDF")
                outputs.append(single_name)

        msg = self._tr('info_img2pdf_done', path=out_path)
        if self.delete_source.get():
            msg += self._delete_source_files(imgs, outputs)
        self.ui_queue.put(('info', msg))

    # ---------- PDF 合并 ----------
    def run_pdfmerge(self, output_name):
        pdfs = self.selected_files
        total = len(pdfs)
        out_dir = pdfs[0].parent.parent
        out_path = out_dir / output_name
        writer = pypdf.PdfWriter()
        processed = 0
        for p in pdfs:
            self.ui_queue.put(('status', self._tr('status_merging', name=p.name)))
            reader = pypdf.PdfReader(str(p))
            for page in reader.pages:
                writer.add_page(page)
            processed += 1
            self.ui_queue.put(('progress', (processed, total)))
        with open(out_path, 'wb') as f:
            writer.write(f)

        msg = self._tr('info_pdfmerge_done', path=out_path)
        if self.delete_source.get():
            msg += self._delete_source_files(pdfs, [out_path])
        self.ui_queue.put(('info', msg))

    def _delete_source_files(self, sources, outputs):
        output_paths = {str(p.resolve()) for p in outputs}
        deleted = 0
        failed = []
        for p in sources:
            try:
                if str(p.resolve()) in output_paths:
                    continue
                if p.exists():
                    p.unlink()
                    deleted += 1
            except Exception as e:
                failed.append(f"{p.name}（{e}）")
        extra = self._tr('deleted_source', n=deleted)
        if failed:
            extra += self._tr('delete_failed', n=len(failed), detail='\n'.join(failed))
        return extra


def _resource_path(relative_path: str) -> str:
    """获取资源文件的绝对路径，兼容开发态和 PyInstaller 打包态。"""
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def main():
    if DND_OK:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    icon_path = _resource_path('app_icon.ico')
    if os.path.exists(icon_path):
        try:
            root.iconbitmap(icon_path)
        except Exception:
            pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
