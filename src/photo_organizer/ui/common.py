"""사진 도구의 공통 테마와 화면. 별도 설정 파일을 만들지 않습니다."""
from __future__ import annotations

import base64
import math
import os
from pathlib import Path
import struct
import tkinter as tk
from tkinter import font as tkfont, messagebox, ttk
import zlib
from photo_organizer.paths import resource_root

WHITE, SIDEBAR, INK = "#ffffff", "#f2f3f5", "#23252b"
MUTED, BLUE, LINE = "#777b86", "#007aff", "#e5e6eb"
TOOLS = {
    "date": ("날짜별 정리", "photo_date"),
    "type": ("파일 분류", "file_sort"),
    "pair": ("RAW · JPG 정리", "raw_jpg"),
}
_bundled_fonts_loaded = False


def _load_bundled_fonts():
    """폰트가 없는 PC에서도 프로세스 안에서만 사용합니다. 시스템에는 설치하지 않습니다."""
    global _bundled_fonts_loaded
    if _bundled_fonts_loaded or os.name != "nt":
        return
    import ctypes as ct
    gdi = ct.WinDLL("gdi32")
    gdi.AddFontResourceExW.argtypes = [ct.c_wchar_p, ct.c_uint, ct.c_void_p]
    gdi.AddFontResourceExW.restype = ct.c_int
    folder = resource_root() / "assets" / "fonts"
    for name in ("Regular", "Medium", "Bold"):
        path = folder / f"NotoSansKR-{name}.ttf"
        if path.is_file():
            gdi.AddFontResourceExW(str(path), 0x10, None)
    _bundled_fonts_loaded = True


def _typography(root):
    """화면 역할별 서체. Medium은 실제 중간 굵기 패밀리를 사용합니다."""
    _load_bundled_fonts()
    available = set(tkfont.families(root))
    fallback = tkfont.nametofont("TkDefaultFont", root).actual("family")
    regular = next((name for name in ("Photo Organizer UI", "Noto Sans KR", "나눔스퀘어 네오 Regular", "맑은 고딕") if name in available), fallback)
    requested_medium = "Photo Organizer UI Medium" if regular == "Photo Organizer UI" else "Noto Sans KR Medium"
    medium = requested_medium if requested_medium in available and regular in {"Photo Organizer UI", "Noto Sans KR"} else regular
    medium_weight = "normal" if medium != regular else "bold"
    roles = {
        "body": (regular, 10, "normal"),
        "title": (regular, 21, "bold"),
        "brand": (regular, 13, "bold"),
        "modal": (regular, 17, "bold"),
        "section": (medium, 11, medium_weight),
        "control": (medium, 10, medium_weight),
        "caption": (regular, 9, "normal"),
        "column": (medium, 9, medium_weight),
        "link": (medium, 9, medium_weight),
        "empty": (regular, 11, "normal"),
    }
    fonts = {role: tkfont.Font(root=root, family=family, size=size, weight=weight)
             for role, (family, size, weight) in roles.items()}
    root._photo_fonts = fonts
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkTooltipFont"):
        tkfont.nametofont(name, root).configure(family=regular, size=9 if name == "TkTooltipFont" else 10, weight="normal")
    tkfont.nametofont("TkHeadingFont", root).configure(family=medium, size=10, weight=medium_weight)
    root.option_add("*TCombobox*Listbox.font", fonts["body"])
    return fonts


def enable_dpi_awareness():
    if os.name != "nt":
        return
    _load_bundled_fonts()
    import ctypes as ct
    user32 = ct.WinDLL("user32")
    try:
        aware = user32.SetProcessDpiAwarenessContext
        aware.argtypes = [ct.c_void_p]
        aware.restype = ct.c_int
        aware(ct.c_void_p(-4))
    except AttributeError:
        user32.SetProcessDPIAware()


def _rounded_texture(root, fill, outline, px, size=26, radius=7, check=False, *, width=None, background=None):
    """둥근 테마 비트맵. 넓은 불투명 배경으로 Windows의 반복 타일 그리기를 줄입니다."""
    height, image_width = px(size), px(width if width is not None else size)
    radius = min(px(radius), height // 2, image_width // 2)
    edge_width = max(1, px(1))
    fill_rgb = tuple(bytes.fromhex(fill.lstrip("#")))
    edge_rgb = tuple(bytes.fromhex(outline.lstrip("#")))
    backdrop = tuple(bytes.fromhex(background.lstrip("#"))) if background else None

    def pixel(x, y):
        dx = max(radius - x - .5, 0, x + .5 - (image_width - radius))
        dy = max(radius - y - .5, 0, y + .5 - (height - radius))
        distance = math.hypot(dx, dy)
        alpha = round(255 * max(0, min(1, radius + .5 - distance)))
        border = min(x, y, image_width - 1 - x, height - 1 - y) < edge_width or distance > radius - edge_width
        color = edge_rgb if border else fill_rgb
        if check:
            for ax, ay, bx, by in ((4, 8, 7, 11), (7, 11, 12, 5)):
                ax, ay, bx, by = (px(value) for value in (ax, ay, bx, by))
                t = max(0, min(1, ((x-ax)*(bx-ax)+(y-ay)*(by-ay)) / ((bx-ax)**2+(by-ay)**2)))
                if math.hypot(x-ax-t*(bx-ax), y-ay-t*(by-ay)) <= edge_width * .8:
                    color = (255, 255, 255)
        if backdrop is not None:
            color = tuple((channel * alpha + base * (255-alpha) + 127) // 255 for channel, base in zip(color, backdrop))
            alpha = 255
        return bytes((*color, alpha))

    rows = []
    for y in range(height):
        if check:
            row = b"".join(pixel(x, y) for x in range(image_width))
        else:
            left = [pixel(x, y) for x in range(radius)]
            middle_color = edge_rgb if y < edge_width or y >= height - edge_width else fill_rgb
            middle = bytes((*middle_color, 255)) * (image_width - 2 * radius)
            row = b"".join(left) + middle + b"".join(reversed(left))
        rows.append(b"\0" + row)
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", image_width, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b"")
    return tk.PhotoImage(master=root, data=base64.b64encode(png).decode("ascii"))


def _theme(root, px):
    if getattr(root, "_photo_theme_ready", False):
        return
    fonts = _typography(root)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=fonts["body"], background=WHITE, foreground=INK)
    style.configure("TFrame", background=WHITE)
    style.configure("TLabel", background=WHITE, foreground=INK)
    style.configure("Title.TLabel", font=fonts["title"])
    style.configure("ModalTitle.TLabel", font=fonts["modal"])
    style.configure("Heading.TLabel", font=fonts["section"])
    style.configure("Subtitle.TLabel", foreground="#69707d", font=fonts["body"])
    style.configure("Muted.TLabel", foreground=MUTED, font=fonts["caption"])
    style.configure("Selection.TLabel", font=fonts["control"])
    style.configure("Empty.TLabel", foreground=MUTED, font=fonts["empty"])
    root._photo_style_images = []
    palettes = {
        "TButton": [(WHITE, "#d9dce3"), ("#f4f5f7", "#cbd0d9"), ("#e9edf2", "#b8c5d8"), ("#f5f5f7", "#e7e8ec")],
        "Primary.TButton": [(BLUE, BLUE), ("#006ee6", "#006ee6"), ("#005dca", "#005dca"), ("#e9ebef", "#e9ebef")],
        "Sidebar.TButton": [(SIDEBAR, SIDEBAR), ("#e7e9ed", "#e7e9ed"), ("#dce2eb", "#dce2eb"), (SIDEBAR, SIDEBAR)],
        "Active.Sidebar.TButton": [("#dceaff", "#dceaff"), ("#cfe3ff", "#cfe3ff"), ("#c3dcff", "#c3dcff"), ("#e3e9f1", "#e3e9f1")],
    }
    for index, (name, palette) in enumerate(palettes.items()):
        surface = SIDEBAR if "Sidebar" in name else WHITE
        images = [_rounded_texture(root, fill, border, px, size=48, width=1024, background=surface)
                  for fill, border in palette]
        images.append(_rounded_texture(root, palette[0][0], "#005dca" if name == "Primary.TButton" else BLUE,
                                       px, size=48, width=1024, background=surface))
        root._photo_style_images.extend(images)
        element = f"PhotoButton{index}.border"
        style.element_create(element, "image", images[0], ("disabled", images[3]), ("pressed", images[2]),
                             ("active", images[1]), ("focus", images[4]), border=px(8), padding=px(6),
                             width=0, height=0, sticky="nsew")
        style.layout(name, [(element, {"sticky": "nsew", "children": [
            ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})]})])
        sidebar, primary = "Sidebar" in name, name == "Primary.TButton"
        color = WHITE if primary else ("#0063d2" if name.startswith("Active") else INK)
        style.configure(name, padding=(px(12), px(6 if sidebar else 5)), anchor="w" if sidebar else "center",
                        font=fonts["control"] if primary or name.startswith("Active") or not sidebar else fonts["body"], foreground=color,
                        background=SIDEBAR if sidebar else WHITE)
        style.map(name, foreground=[("disabled", "#a1a5ae"), ("!disabled", color)])
    style.configure("Text.TButton", padding=(px(8), px(5)), background=WHITE, foreground=BLUE,
                    borderwidth=0, relief="flat", font=fonts["link"])
    style.layout("Text.TButton", [("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})])
    style.map("Text.TButton", foreground=[("disabled", "#b0b4bd"), ("active", "#005dca")], background=[("active", "#f0f5ff"), ("focus", "#e6f0ff")])
    field = _rounded_texture(root, "#f7f8fa", "#e0e3e9", px, size=48, width=1024, background=WHITE)
    root._photo_style_images.append(field)
    style.element_create("PhotoEntry.field", "image", field, border=px(8), padding=px(6),
                         width=0, height=0, sticky="nsew")
    style.layout("TEntry", [("PhotoEntry.field", {"sticky": "nsew", "children": [
        ("Entry.padding", {"sticky": "nsew", "children": [("Entry.textarea", {"sticky": "nsew"})]})]})])
    style.configure("TEntry", padding=(px(12), px(5)), foreground="#424752", background=WHITE, borderwidth=0, font=fonts["body"])
    style.map("TEntry", fieldbackground=[("readonly", "#f7f8fa")])
    style.configure("TCombobox", font=fonts["body"], padding=(px(10), px(8)), arrowsize=px(13), fieldbackground=WHITE,
                    bordercolor="#d9dce3", lightcolor=WHITE, darkcolor=WHITE, arrowcolor=MUTED)
    style.map("TCombobox", fieldbackground=[("readonly", WHITE)], selectbackground=[("readonly", WHITE)], selectforeground=[("readonly", INK)])
    style.configure("TCheckbutton", font=fonts["control"], background=WHITE, foreground="#505562", padding=(0, px(3)), indicatorsize=px(14))
    style.map("TCheckbutton", background=[("active", WHITE)], indicatorbackground=[("selected", BLUE), ("!selected", WHITE)], indicatorforeground=[("selected", WHITE)])
    style.configure("Treeview", font=fonts["body"], rowheight=px(38), background=WHITE, fieldbackground=WHITE,
                    foreground=INK, borderwidth=0, relief="flat", indent=0)
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nsew"})])
    style.layout("Treeview.Item", [("Treeitem.padding", {"sticky": "nsew", "children": [
        ("Treeitem.image", {"side": "left", "sticky": ""})]})])
    style.configure("Treeview.Item", padding=(px(14), 0))
    root._photo_check_images = {
        False: _rounded_texture(root, WHITE, "#cbd0da", px, 16, 4),
        True: _rounded_texture(root, BLUE, BLUE, px, 16, 4, check=True),
    }
    style.element_create("PhotoCheck.indicator", "image", root._photo_check_images[False],
                         ("selected", root._photo_check_images[True]))
    style.layout("TCheckbutton", [("Checkbutton.padding", {"sticky": "nsew", "children": [
        ("PhotoCheck.indicator", {"side": "left", "sticky": ""}),
        ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [
            ("Checkbutton.label", {"sticky": "nsew"})]})]})])
    style.configure("Treeview.Heading", font=fonts["column"], padding=(px(10), px(11)), background="#f6f7f9",
                    foreground="#747986", relief="flat", borderwidth=0)
    style.map("Treeview.Heading", background=[("active", "#eef0f4")])
    style.map("Treeview", background=[("selected", "#e6f0ff")], foreground=[("selected", "#174477")])
    for direction in ("Vertical", "Horizontal"):
        style.configure(direction + ".TScrollbar", width=px(10), arrowsize=0, borderwidth=0, troughcolor=WHITE,
                        background="#c9ccd2", lightcolor="#c9ccd2", darkcolor="#c9ccd2", bordercolor=WHITE, gripcount=0)
    style.configure("TProgressbar", background=BLUE, troughcolor="#edf2fa", borderwidth=0, thickness=px(3))
    style.configure("TSeparator", background=LINE, lightcolor=LINE, darkcolor=LINE, bordercolor=LINE)
    root._photo_theme_ready = True


def configure_window(root: tk.Tk, title: str):
    scale = max(1.0, root.winfo_fpixels("1i") / 96)
    px = lambda number: round(number * scale)
    root.title(title)
    if not getattr(root, "_photo_theme_ready", False):
        width = min(px(1160), root.winfo_screenwidth() - px(60))
        height = min(px(740), root.winfo_screenheight() - px(80))
        root.geometry(f"{width}x{height}")
        root.minsize(min(px(1000), width), min(px(620), height))
    root.configure(background=WHITE)
    _theme(root, px)
    return px


def switch_tool(app, tool):
    """작업 중 전환을 막고, 같은 창에서 선택 폴더를 이어받습니다."""
    if app.busy or app.closed or app.shell.tool == tool:
        return None
    if tool == "pair":
        from photo_organizer.ui.pairs import PhotoCleanupApp
        factory = lambda root, folder: PhotoCleanupApp(root, initial_folder=folder)
    else:
        from photo_organizer.ui.organizer import OrganizerApp
        factory = lambda root, folder: OrganizerApp(root, tool, initial_folder=folder)
    root = app.root
    folder = Path(app.folder.get()) if app.folder.get() else None
    if app.shell.tool in {"date", "type"}:
        root._photo_view_options = app.view_options
    if getattr(app, "view_dialog", None) is not None:
        app.view_dialog.close()
    cancel_callbacks(app)
    root.unbind("<Control-o>", app.shell.open_binding)
    close_command = root.protocol("WM_DELETE_WINDOW")
    if close_command:
        root.deletecommand(close_command)
    app.closed = True
    for child in root.winfo_children():
        child.destroy()
    return factory(root, folder)


def cancel_callbacks(app):
    app.progress.stop()
    for name in ("poll_id", "initial_scan_id"):
        callback = getattr(app, name, None)
        if callback:
            try:
                app.root.after_cancel(callback)
            except tk.TclError:
                pass


class Workspace:
    def __init__(self, app, tool, px):
        self.app, self.tool, self.px = app, tool, px
        root = app.root
        fonts = root._photo_fonts
        root._photo_current_app = app
        self.images = []
        self.frame = tk.Frame(root, background=WHITE)
        self.frame.pack(fill="both", expand=True)
        sidebar = tk.Frame(self.frame, background=SIDEBAR, width=px(194))
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Frame(self.frame, background=LINE, width=1).pack(side="left", fill="y")
        self.page = ttk.Frame(self.frame, padding=(px(26), px(22), px(26), px(20)))
        self.page.pack(side="left", fill="both", expand=True)
        self.page.columnconfigure(0, weight=1)
        self.page.rowconfigure(4, weight=1)
        brand = tk.Frame(sidebar, background=SIDEBAR)
        brand.pack(fill="x", padx=px(20), pady=(px(24), px(30)))
        icon = self.icon(tool, px(29))
        tk.Label(brand, image=icon, background=SIDEBAR).pack(side="left", padx=(0, px(8)))
        tk.Label(brand, text="사진 도구", font=fonts["brand"], foreground=INK, background=SIDEBAR).pack(side="left")
        tk.Label(sidebar, text="정리 도구", font=fonts["caption"], foreground=MUTED, background=SIDEBAR, anchor="w").pack(fill="x", padx=px(22), pady=(0, px(8)))
        self.nav_buttons = {}
        for key, (label, _) in TOOLS.items():
            button = ttk.Button(sidebar, text="  " + label, image=self.icon(key, px(19)), compound="left",
                                style="Active.Sidebar.TButton" if key == tool else "Sidebar.TButton",
                                command=lambda key=key: switch_tool(app, key))
            button.pack(fill="x", padx=px(10), pady=px(3))
            self.nav_buttons[key] = button
        tk.Frame(sidebar, background="#dfe2e7", height=1).pack(fill="x", padx=px(18), pady=(px(22), px(24)))
        self.steps = []
        for index, text in enumerate(("폴더 선택", "미리보기", "정리하기"), 1):
            row = tk.Frame(sidebar, background=SIDEBAR)
            row.pack(fill="x", padx=px(23), pady=(0, px(18)))
            circle = tk.Canvas(row, width=px(24), height=px(24), background=SIDEBAR, highlightthickness=0)
            circle.pack(side="left")
            label = tk.Label(row, text=text, font=fonts["body"], background=SIDEBAR, foreground=MUTED)
            label.pack(side="left", padx=px(10))
            self.steps.append((circle, label))
        help_button = ttk.Button(sidebar, text="ⓘ  사용 안내", style="Sidebar.TButton", command=self.help)
        help_button.pack(side="bottom", fill="x", padx=px(12), pady=px(17))
        self.open_binding = root.bind("<Control-o>", lambda event: app.choose_folder())
        icon_path = resource_root() / "assets" / "icons" / (TOOLS[tool][1] + ".ico")
        if os.name == "nt" and icon_path.exists():
            root.iconbitmap(default=str(icon_path))

    def icon(self, tool, size):
        path = resource_root() / "assets" / "icons" / (TOOLS[tool][1] + ".ico")
        if not path.exists():
            return ""
        root = self.app.root
        cache = getattr(root, "_photo_icon_cache", {})
        key = (tool, size)
        if key in cache:
            return cache[key]
        data = path.read_bytes()
        count = struct.unpack_from("<H", data, 4)[0]
        frames = [struct.unpack_from("<BBBBHHII", data, 6 + i * 16) for i in range(count)]
        frame = min(frames, key=lambda item: (abs((item[0] or 256) - size), -(item[0] or 256)))
        png = data[frame[7]:frame[7] + frame[6]]
        image = tk.PhotoImage(master=root, data=base64.b64encode(png).decode("ascii"))
        cache[key] = image
        root._photo_icon_cache = cache
        self.images.append(image)
        return image

    def set_state(self, busy, stage):
        for button in self.nav_buttons.values():
            button.configure(state="disabled" if busy else "normal")
        for index, (circle, label) in enumerate(self.steps, 1):
            active, done = index == stage, index < stage
            circle.delete("all")
            end = self.px(23)
            circle.create_oval(1, 1, end, end, fill=BLUE if active else ("#dceaff" if done else "#e5e7ec"), outline="")
            circle.create_text(self.px(12), self.px(12), text="✓" if done else str(index),
                               fill=WHITE if active else (BLUE if done else MUTED), font=self.app.root._photo_fonts["column"])
            label.configure(foreground=BLUE if active else MUTED,
                            font=self.app.root._photo_fonts["control" if active else "body"])

    def help(self):
        detail = {
            "date": "촬영 날짜별 폴더로 이동합니다. NEF의 수정한 날짜는 유지합니다.",
            "type": "선택한 폴더 안의 JPG·NEF·MOV 파일을 종류별로 분류합니다.",
            "pair": "한쪽 형식을 지운 뒤, 짝이 없는 파일을 휴지통으로 보냅니다.\n처음부터 한 형식으로만 찍은 사진도 표시되므로 확인해 주세요.",
        }[self.tool]
        messagebox.showinfo("사용 안내", "1. 폴더를 선택하세요.\n2. 목록을 확인하고 남길 파일의 체크를 해제하세요.\n3. 오른쪽 아래 버튼을 누르고 확인하세요.\n\n" + detail, parent=self.app.root)


def file_table(parent, columns, px, empty_text):
    frame = ttk.Frame(parent)
    frame.grid(row=4, column=0, sticky="nsew")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    tree = ttk.Treeview(frame, columns=tuple(item[0] for item in columns), show="tree headings", selectmode="browse")
    tree.heading("#0", text="선택")
    tree.column("#0", width=px(46), minwidth=px(46), stretch=False, anchor="center")
    for name, label, width, stretch, anchor in columns:
        tree.heading(name, text=label, anchor=anchor)
        tree.column(name, width=px(width), minwidth=px(65), stretch=stretch, anchor=anchor)
    tree.grid(row=0, column=0, sticky="nsew")
    vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    horizontal.grid(row=1, column=0, sticky="ew")
    def scroll_state(scrollbar, first, last):
        scrollbar.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            scrollbar.grid_remove()
        else:
            scrollbar.grid()
    tree.configure(yscrollcommand=lambda first, last: scroll_state(vertical, first, last),
                   xscrollcommand=lambda first, last: scroll_state(horizontal, first, last))
    tree.tag_configure("even", background=WHITE)
    tree.tag_configure("odd", background="#f7f8fa")
    tree.tag_configure("skipped", foreground="#9ca1ac")
    empty = ttk.Label(frame, text=empty_text, style="Empty.TLabel", justify="center", anchor="center")
    empty.place(relx=.5, rely=.5, anchor="center")
    return tree, empty


def checkbox(root, checked):
    return root._photo_check_images[bool(checked)]


def set_checked(tree, item, checked):
    root = tree.winfo_toplevel()
    tree.item(item, text="☑" if checked else "☐", image=checkbox(root, checked))
