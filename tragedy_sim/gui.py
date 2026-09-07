"""Native Tk GUI for local hotseat games. No network or third-party packages."""

import argparse
from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .cards import ACTOR_NAMES, LOCATIONS, deck
from .catalog import INCIDENT_NAMES, MODULES, ROLE_NAMES
from .hotseat import (HotseatSession, NEXT_LABELS, PHASE_NAMES, character_details,
                      module_capability, module_roles, public_knowledge, public_log,
                      public_rules, secret_dossier, target_name)
from .replay import ReplayArchive, ReplaySession


BG = "#101722"
PANEL = "#182332"
CARD = "#213144"
LINE = "#34465d"
INK = "#eef3f8"
MUTED = "#acbdd0"
ACCENT = "#78dfca"
DANGER = "#ffabab"
AREA_COLORS = {"hospital": "#a9d2ff", "shrine": "#e2b6de", "city": "#f0cc8d", "school": "#a5debb"}


class GuiArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(f"{message}\n{self.format_usage().strip()}")


class ScrollFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg=PANEL, highlightthickness=0, width=1, height=1)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window(0, 0, anchor="nw", window=self.body)
        self.canvas.bind("<Configure>", self._resize)
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

    def _resize(self, event):
        self.canvas.itemconfigure(self.window, width=event.width)


def text_panel(parent, height=8):
    frame = ttk.Frame(parent)
    text = tk.Text(frame, bg=PANEL, fg=INK, insertbackground=INK, selectbackground=LINE,
                   relief="flat", wrap="word", font=("Microsoft YaHei UI", 10), height=height,
                   width=1, padx=12, pady=12, state="disabled", undo=False, exportselection=False)
    bar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=bar.set)
    text.pack(side="left", fill="both", expand=True)
    bar.pack(side="right", fill="y")
    return frame, text


def set_text(widget, value, *, bottom=False):
    if widget.get("1.0", "end-1c") == value:
        return
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", value)
    widget.configure(state="disabled")
    if bottom:
        widget.see("end")


class TragedyApp:
    def __init__(self, root, game=None, *, session=None):
        self.root = root
        self.session = session if session is not None else HotseatSession(game)
        self.selected_target = None
        self.selected_card = None
        self.selected_option = None
        self.inspect_target = None
        self._focus_job = None
        self._error = ""
        self.private_notebook = None
        self.controls = {}  # Named widgets also permit small display-level smoke tests.
        self._style()
        root.title("悲剧轮回 · 本地热座")
        width = min(1440, root.winfo_screenwidth() - 80)
        height = min(940, root.winfo_screenheight() - 90)
        root.geometry(f"{width}x{height}")
        root.minsize(min(1100, width), min(740, height))
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Escape>", lambda e: self.hide())
        root.bind("<FocusOut>", self._focus_out, add="+")
        root.bind("<Unmap>", self._unmap, add="+")
        root.bind("<MouseWheel>", self._wheel, add="+")
        root.bind("<Control-s>", lambda e: self.save())
        root.bind("<Control-o>", lambda e: self.open_file(False))
        self._layout()
        self.render()

    def _style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=PANEL, foreground=INK, font=("Microsoft YaHei UI", 10))
        style.configure("TFrame", background=PANEL)
        style.configure("TLabel", background=PANEL, foreground=INK)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 21, "bold"), background=BG)
        style.configure("Header.TFrame", background=BG)
        style.configure("Header.TLabel", background=BG, foreground=MUTED)
        style.configure("Section.TLabel", font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("TButton", background=CARD, foreground=INK, bordercolor=LINE, padding=(12, 8))
        style.map("TButton", background=[("active", LINE), ("pressed", LINE)], foreground=[("disabled", "#778899")])
        style.configure("Accent.TButton", background=ACCENT, foreground=BG, font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#a0efdf"), ("disabled", LINE)], foreground=[("disabled", MUTED)])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(12, 8), background=CARD)
        style.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", ACCENT)])
        style.configure("TCombobox", fieldbackground=CARD, background=CARD, arrowcolor=INK, padding=7)
        style.map("TCombobox", fieldbackground=[("readonly", CARD)], foreground=[("readonly", INK)], selectbackground=[("readonly", CARD)])
        style.configure("TPanedwindow", background=BG)
        style.configure("Vertical.TScrollbar", background=LINE, troughcolor=PANEL, arrowcolor=MUTED)
        self.root.option_add("*TCombobox*Listbox.background", CARD)
        self.root.option_add("*TCombobox*Listbox.foreground", INK)
        self.root.option_add("*TCombobox*Listbox.selectBackground", LINE)

    def _layout(self):
        header = ttk.Frame(self.root, style="Header.TFrame", padding=(20, 14))
        header.pack(fill="x")
        brand = ttk.Frame(header, style="Header.TFrame")
        brand.pack(side="left")
        ttk.Label(brand, text="悲剧轮回", style="Title.TLabel").pack(anchor="w")
        ttk.Label(brand, text="TRAGEDY LOOPER  /  本地热座", style="Header.TLabel").pack(anchor="w")
        tools = ttk.Frame(header, style="Header.TFrame")
        tools.pack(side="right")
        for title, command in (("新对局", self.new_game), ("载入剧本", lambda: self.open_file(True)),
                               ("恢复存档", lambda: self.open_file(False)), ("打开回放", self.open_replay),
                               ("另存对局", self.save)):
            ttk.Button(tools, text=title, command=command).pack(side="left", padx=3)
        self.controls["hide"] = ttk.Button(tools, text="遮挡 / 交接  Esc", command=self.hide, style="Accent.TButton")
        self.controls["hide"].pack(side="left", padx=(10, 0))

        strip = ttk.Frame(self.root, padding=(16, 10))
        strip.pack(fill="x", padx=20, pady=(0, 12))
        self.match_title = ttk.Label(strip, style="Section.TLabel")
        self.match_title.pack(side="left")
        self.turn_label = ttk.Label(strip, foreground=ACCENT)
        self.turn_label.pack(side="right")

        self.main_panes = ttk.PanedWindow(self.root, orient="horizontal")
        self.main_panes.pack(fill="both", expand=True, padx=20)
        left = ttk.Frame(self.main_panes)
        self.right = ttk.Frame(self.main_panes, width=435)
        self.main_panes.add(left, weight=3)
        self.main_panes.add(self.right, weight=2)

        self.timeline = ttk.Frame(left, padding=(10, 10))
        self.timeline.pack(fill="x")
        self.left_panes = ttk.PanedWindow(left, orient="vertical")
        self.left_panes.pack(fill="both", expand=True)
        board_area = ttk.Frame(self.left_panes)
        label = ttk.Frame(board_area, padding=(12, 8))
        label.pack(fill="x")
        ttk.Label(label, text="公共棋盘", style="Section.TLabel").pack(side="left")
        ttk.Label(label, text="点击角色查看卡面信息 · 暗牌不公开内容", style="Muted.TLabel").pack(side="right")
        self.board = ScrollFrame(board_area)
        self.board.pack(fill="both", expand=True)
        self.board.body.columnconfigure((0, 1), weight=1, uniform="areas")
        self.left_panes.add(board_area, weight=3)

        self.public_tabs = ttk.Notebook(self.left_panes)
        self.log_frame, self.log_text = text_panel(self.public_tabs, 7)
        self.details_frame, self.details_text = text_panel(self.public_tabs, 7)
        knowledge_frame, self.knowledge_text = text_panel(self.public_tabs, 7)
        rules_frame, self.rules_text = text_panel(self.public_tabs, 7)
        help_frame, help_text = text_panel(self.public_tabs, 7)
        for frame, title in ((self.log_frame, "结算记录"), (self.details_frame, "角色信息"),
                             (knowledge_frame, "已知信息 / 限次"), (rules_frame, "公开规则"), (help_frame, "热座指南")):
            self.public_tabs.add(frame, text=title)
        set_text(help_text, "1. 所有人先查看公共棋盘和事件日程。默认没有任何秘密展开。\n\n"
                 "2. 操作区提示轮到谁，将屏幕交给该玩家，其余玩家移开视线，再点“我是该玩家”。\n\n"
                 "3. 出牌时先选手牌，再选目标，最后确认放置。需要选择的能力与事件会列出合法选项。\n\n"
                 "4. 换座位自动遮挡；同座位可继续行动。Esc 或右上方按钮可随时遮挡，切换到其他应用也会遮挡。\n\n"
                 "5. 剧作家在自己操作时可查看“剧本 · 私密”页。主人公只能查看自己的手牌。\n\n"
                 "6. 完整对局须按阶段推进；不提供悔棋、跳过必选结算或任意改数值。\n\n"
                 "7. 新对局、加载和退出前会询问是否保存。存档含全部秘密，请只保存在本地，不要给主人公看。\n\n"
                 "这是防止误露信息的本地遮挡，不是登录验证。旁观者、屏幕共享、截图或读取存档仍可能泄露秘密。\n"
                 "默认由四个座位 m/a/b/c 操作；人数不足时可以一人控制多个座位。")
        self.left_panes.add(self.public_tabs, weight=2)

        self.private_header = ttk.Frame(self.right, padding=(16, 14))
        self.private_header.pack(fill="x")
        self.seat_title = ttk.Label(self.private_header, style="Section.TLabel")
        self.seat_title.pack(anchor="w")
        self.seat_subtitle = ttk.Label(self.private_header, style="Muted.TLabel", wraplength=385)
        self.seat_subtitle.pack(anchor="w", pady=(5, 0))
        self.private = ttk.Frame(self.right, padding=(12, 0, 12, 12))
        self.private.pack(fill="both", expand=True)
        status = ttk.Frame(self.root, style="Header.TFrame", padding=(20, 9))
        status.pack(fill="x")
        self.status = ttk.Label(status, style="Header.TLabel")
        self.status.pack(side="left")
        self.discussion = ttk.Label(status, style="Header.TLabel")
        self.discussion.pack(side="right")

    def render(self):
        view = self.session.public_view()
        phase = PHASE_NAMES[view["phase"]]
        replay = getattr(self.session, "replay_mode", False)
        mode = "回放" if replay else "本地热座"
        self.controls["hide"].configure(text="只读回放" if replay else "遮挡 / 交接  Esc",
                                        state="disabled" if replay else "normal")
        self.root.title(f"悲剧轮回 · {view['module']} {mode}")
        self.match_title.configure(text=f"{view['title']}  /  {view['module']}" + ("  ·  只读回放" if replay else ""))
        ex_status = f"  ·  Ex 槽 {view['ex_gauge']}" if view["module"] in ("MC", "WM", "AHR") else ""
        if view["module"] == "AHR":
            ex_status += "（表世界）" if view["world"] == "surface" else "（里世界）"
        self.turn_label.configure(text=f"轮回 {view['loop']}/{view['loops']}   第 {view['round']}/{view['days']} 天  ·  {phase}{ex_status}")
        self.discussion.configure(text=(f"回放位置：{self.session.index}/{self.session.length}"
                                        if replay else
                                        f"领队：{ACTOR_NAMES[view['leader']]}   ·   讨论：{'允许' if view['table_talk'] else '受限（真人遵守）'}"))
        normal_status = (f"只读完整信息回放 · 第 {self.session.index}/{self.session.length} 个决策"
                         if replay else
                         ("存在未保存的操作  ·  Ctrl+S 另存对局" if self.session.dirty else "本地运行 · 无联网 · 存档包含秘密"))
        self.status.configure(text=self._error or normal_status,
                              foreground=DANGER if self._error else MUTED)
        self._render_timeline(view)
        self._render_board(view)
        at_bottom = self.log_text.yview()[1] >= 0.98
        set_text(self.log_text, public_log(view), bottom=at_bottom)
        set_text(self.knowledge_text, public_knowledge(view))
        set_text(self.rules_text, public_rules(view["module"]))
        if self.inspect_target in view["characters"]:
            set_text(self.details_text, character_details(view, self.inspect_target))
        elif self.inspect_target in LOCATIONS:
            loc = self.inspect_target
            counter_name = "尸体标记" if view["module"] == "HSA" else "密谋"
            curse = f"\n诅咒牌：{view['board_ex'][loc]}" if view["module"] == "HSA" else ""
            set_text(self.details_text, f"{LOCATIONS[loc]}\n\n{counter_name}：{view['locations'][loc]}{curse}\n\n任何行动牌都可放在地点佯攻；只有密谋及其禁止在地点上有效。")
        else:
            set_text(self.details_text, "点击棋盘上的角色，查看其初始位置、禁行区域、属性与完整能力。\n\n这里始终只显示公开信息。")
        self._render_private(view)
        # A destroyed button must not leave the app with no focus and trigger
        # the focus-loss privacy curtain immediately after a successful action.
        self.root.focus_set()

    def _render_timeline(self, view):
        for child in self.timeline.winfo_children():
            child.destroy()
        ttk.Label(self.timeline, text="事件日程", style="Muted.TLabel").pack(anchor="w", pady=(0, 6))
        days = ttk.Frame(self.timeline)
        days.pack(fill="x")
        schedule = {i["day"]: i for i in view["schedule"]}
        records = {i["day"]: i for i in view["incidents"]}
        for day in range(1, view["days"] + 1):
            days.columnconfigure(day - 1, weight=1, uniform="day")
            item, record = schedule.get(day), records.get(day)
            name = (INCIDENT_NAMES[item["kind"]]
                    + (f"·{LOCATIONS[item['board']]}" if "board" in item else "")) if item else "无预定事件"
            status = "待结算" if item else "—"
            if record:
                status = "已发生" if record["happened"] else "未发生"
                if record["happened"] and not record["effective"]:
                    status = "结算中" if view["phase"] == "decision" and day == view["round"] else "发生 · 无效果"
            current = day == view["round"] and view["phase"] not in ("final_guess", "game_over")
            tk.Label(days, text=f"第 {day} 天\n{name}\n{status}", bg=CARD if current else PANEL,
                     fg=ACCENT if current else MUTED, font=("Microsoft YaHei UI", 9), padx=4, pady=5,
                     highlightthickness=1, highlightbackground=ACCENT if current else LINE).grid(row=0, column=day - 1, sticky="nsew", padx=2)

    def _render_board(self, view):
        for child in self.board.body.winfo_children():
            child.destroy()
        for i, (loc, name) in enumerate(LOCATIONS.items()):
            area = tk.Frame(self.board.body, bg=PANEL, highlightthickness=1, highlightbackground=LINE, padx=8, pady=8)
            area.grid(row=i // 2, column=i % 2, sticky="nsew", padx=6, pady=6)
            sealed = next((item["through"] for item in view.get("sealed_boards", [])
                           if item["board"] == loc), None)
            seal_text = f"   ·   封锁至第 {sealed} 天" if sealed is not None else ""
            counter_name = "尸体" if view["module"] == "HSA" else "密谋"
            curse = (f"   ·   诅咒 {view['board_ex'][loc]}"
                     if view["module"] == "HSA" and view["board_ex"][loc] else "")
            title = tk.Button(area, text=f"{name}   ·   {counter_name} {view['locations'][loc]}{curse}{seal_text}", command=lambda t=loc: self.inspect(t),
                              bg=PANEL, fg=AREA_COLORS[loc], activebackground=CARD, activeforeground=INK, relief="flat",
                              anchor="w", font=("Microsoft YaHei UI", 12, "bold"), cursor="hand2")
            title.pack(fill="x")
            location_plays = self._placements(view, loc)
            if location_plays:
                tk.Label(area, text=location_plays, bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 9), anchor="w").pack(fill="x", pady=(0, 4))
            chars = [c for c in view["characters"].values() if c["location"] == loc]
            if not chars:
                tk.Label(area, text="暂无角色", bg=PANEL, fg=MUTED, pady=12).pack(fill="x")
            for c in chars:
                selected = self.inspect_target == c["id"]
                shell = tk.Frame(area, bg=CARD, highlightbackground=ACCENT if selected else CARD, highlightthickness=1, padx=10, pady=7)
                shell.pack(fill="x", pady=4)
                alive = "存活" if c["alive"] else "尸体"
                name_label = tk.Label(shell, text=f"{c['name']}   {alive}", font=("Microsoft YaHei UI", 11, "bold"),
                                      bg=CARD, fg=INK if c["alive"] else MUTED, anchor="w")
                name_label.pack(fill="x")
                panic = " !" if c["alive"] and c["paranoia"] >= c["paranoia_limit"] else ""
                ex_name = "诅咒" if view["module"] == "HSA" else "Ex"
                ex = f"   {ex_name} {c['ex_cards']}" if c.get("ex_cards") else ""
                locked = "   今日禁止移动" if view.get("movement_locks", {}).get(c["id"]) == view["round"] else ""
                mind = f"   希望 {c['hope']}   绝望 {c['despair']}" if view["module"] in ("AHR", "LL") else ""
                tokens = (("   交友完毕" if c.get("friended_token") else "")
                          + ("   死亡完毕" if c.get("death_token") else ""))
                counts = tk.Label(shell, text=f"友好 {c['goodwill']}   不安 {c['paranoia']}/{c['paranoia_limit']}{panic}   密谋 {c['intrigue']}{mind}   护卫 {c['guard']}{ex}{tokens}{locked}",
                                  bg=CARD, fg=DANGER if panic else MUTED, font=("Microsoft YaHei UI", 10), anchor="w")
                counts.pack(fill="x", pady=(4, 0))
                placements = self._placements(view, c["id"])
                if placements:
                    tk.Label(shell, text=placements, bg=CARD, fg=ACCENT, font=("Microsoft YaHei UI", 9), anchor="w").pack(fill="x", pady=(3, 0))
                for widget in (shell, *shell.winfo_children()):
                    widget.configure(cursor="hand2")
                    widget.bind("<Button-1>", lambda e, t=c["id"]: self.inspect(t))

    @staticmethod
    def _placements(view, target):
        return "  /  ".join(f"{ACTOR_NAMES[p['actor']]} · {deck(p['actor'], view['module'])[p['card']].name if p['card'] else '暗牌'}"
                            for p in view["pending"] if p["target"] == target)

    def _render_private(self, public):
        for child in self.private.winfo_children():
            child.destroy()
        self.controls = {"hide": self.controls["hide"]}
        self.private_notebook = None
        self.selected_card = None
        self.selected_target = None
        self.selected_option = None
        if getattr(self.session, "replay_mode", False):
            self._render_replay_controls()
            return
        seat = self.session.expected_seat
        if public["winner"]:
            winner = ("主人公" if public["winner"] == "protagonists" else "剧作家"
                      if public["winner"] == "mastermind" else
                      f"背叛者（{ACTOR_NAMES[public['winner'].split(':')[1]]}）")
            self.seat_title.configure(text="对局结束")
            self.seat_subtitle.configure(text="结算记录与已知信息仍可查看。")
            ttk.Label(self.private, text=winner + "获胜", foreground=ACCENT, font=("Microsoft YaHei UI", 24, "bold")).pack(pady=(55, 20))
            ttk.Label(self.private, text="故事已经结束。\n可以保存完整记录，或开启新的轮回。", justify="center", style="Muted.TLabel").pack(pady=10)
            ttk.Button(self.private, text="另存完整对局", command=self.save, style="Accent.TButton").pack(pady=10)
            ttk.Button(self.private, text="导出纯文本回放", command=self.export_replay).pack(pady=6)
            ttk.Button(self.private, text="开始新对局", command=self.new_game).pack(pady=6)
            return
        self.seat_title.configure(text=f"{'等待交接' if self.session.seat is None else '当前操作'}  ·  {ACTOR_NAMES[seat]}")
        self.seat_subtitle.configure(text="请其他玩家移开视线；换人前先遮挡。" if self.session.seat is None else "操作区已展开 · Esc 随时遮挡 · 换座位自动遮挡")
        private_view = self.session.private_view()
        if private_view is None:
            ttk.Label(self.private, text="屏幕已遮挡", foreground=ACCENT, font=("Microsoft YaHei UI", 21, "bold")).pack(pady=(52, 14))
            ttk.Label(self.private, text=f"请把操作权交给\n{ACTOR_NAMES[seat]}", font=("Microsoft YaHei UI", 15), justify="center").pack(pady=8)
            ttk.Label(self.private, text="此时公共棋盘可以一起查看。\n准备好后，由当前玩家打开自己的操作区。", justify="center", style="Muted.TLabel").pack(pady=(15, 20))
            self.controls["unlock"] = ttk.Button(self.private, text=f"我是{ACTOR_NAMES[seat]}，打开操作区", command=lambda s=seat: self.unlock(s), style="Accent.TButton")
            self.controls["unlock"].pack(pady=10)
            if self.session.intent:
                ttk.Label(self.private, text="正在交接：提前进入最终猜测", foreground=DANGER).pack(pady=10)
                ttk.Button(self.private, text="取消，返回轮回之间", command=self.cancel_final).pack(pady=6)
            elif public["phase"] == "loop_end" and module_capability(public, "early_final_guess"):
                ttk.Button(self.private, text="领队希望提前最终猜测…", command=self.request_final).pack(pady=16)
            ttk.Label(self.private, text="遮挡只防误露，不是身份验证。\n请勿将私密操作投屏或录制。", justify="center", style="Muted.TLabel").pack(side="bottom", pady=18)
            return

        token = self.session.token
        tabs = ttk.Notebook(self.private)
        tabs.pack(fill="both", expand=True)
        self.private_notebook = tabs
        operation = ttk.Frame(tabs, padding=10)
        tabs.add(operation, text="当前操作")
        if seat == "m":
            dossier_frame, dossier_text = text_panel(tabs)
            tabs.add(dossier_frame, text="剧本 · 私密")
            set_text(dossier_text, secret_dossier(private_view))
        if self.session.intent == "final":
            ttk.Label(operation, text="提前进入最终猜测", style="Section.TLabel").pack(anchor="w", pady=15)
            ttk.Label(operation, text="将放弃所有剩余轮回。必须猜对每个角色的初始身份；一个错误就会输掉对局。\n\n请先与其他主人公达成一致。",
                      wraplength=340, foreground=DANGER).pack(fill="x", pady=12)
            self.controls["final"] = ttk.Button(operation, text="确认放弃余下轮回，开始猜测", command=lambda: self.perform(token, "final"), style="Accent.TButton")
            self.controls["final"].pack(fill="x", pady=10)
            ttk.Button(operation, text="取消", command=self.cancel_final).pack(fill="x")
        elif public["phase"] in ("mastermind", "protagonists"):
            self._render_cards(operation, private_view, token)
        elif public["phase"] == "final_guess":
            self._render_guess(operation, private_view, token)
        else:
            self._render_choices(operation, private_view, token)

    def _render_cards(self, parent, view, token):
        seat = self.session.seat
        own_plays = [p for p in view["pending"] if p["actor"] == seat]
        required = view["action_counts"]["mastermind"] if seat == "m" else 1
        count = f"还需放置 {required - len(own_plays)} 张" if seat == "m" else "本次放置 1 张"
        ttk.Label(parent, text="选择手牌，再选择目标", style="Section.TLabel").pack(anchor="w", pady=(2, 4))
        ttk.Label(parent, text=count + " · 确认前不会出牌", style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        scroll = ScrollFrame(parent)
        scroll.pack(fill="both", expand=True)
        for i, cid in enumerate(view["hand"]):
            c = deck(seat, view["module"])[cid]
            button = ttk.Button(scroll.body, text=c.name + ("\n每轮一次" if c.once_per_loop else "\n每日回手"),
                                command=lambda card=cid: self.select_card(card))
            button.grid(row=i // 2, column=i % 2, sticky="ew", padx=3, pady=4)
            self.controls[f"card:{cid}"] = button
        scroll.body.columnconfigure((0, 1), weight=1, uniform="hand")
        if own_plays:
            placed = "\n".join(f"{deck(seat, view['module'])[p['card']].name} → {target_name(view, p['target'])}" for p in own_plays)
            ttk.Label(scroll.body, text="你已经放置（私密）：\n" + placed, style="Muted.TLabel", wraplength=335).grid(row=(len(view["hand"]) + 1) // 2, column=0, columnspan=2, sticky="ew", padx=5, pady=10)
        ttk.Separator(parent).pack(fill="x", pady=10)
        self.card_summary = ttk.Label(parent, text="尚未选择手牌", foreground=ACCENT, wraplength=350)
        self.card_summary.pack(anchor="w", pady=(0, 6))
        targets = self.session.legal_targets()
        self.target_ids = targets
        self.target_combo = ttk.Combobox(parent, state="readonly", values=[target_name(view, t) + (" · 版图" if t in LOCATIONS else "") for t in targets])
        self.target_combo.pack(fill="x", pady=5)
        self.target_combo.set("请选择一个合法目标")
        self.target_combo.bind("<<ComboboxSelected>>", self.select_play_target)
        self.controls["target"] = self.target_combo
        self.controls["play"] = ttk.Button(parent, text="确认放置暗牌", state="disabled", style="Accent.TButton",
                                           command=lambda: self.perform(token, "play", card=self.selected_card, target=self.selected_target))
        self.controls["play"].pack(fill="x", pady=(10, 0))

    def select_card(self, cid):
        if self.session.private_view() is None:
            return
        self.selected_card = cid
        view = self.session.private_view()
        c = deck(self.session.seat, view["module"])[cid]
        self.card_summary.configure(text="已选：" + c.name + ("（每轮一次，即使无效也消耗）" if c.once_per_loop else ""))
        for key, button in self.controls.items():
            if key.startswith("card:"):
                button.configure(style="Accent.TButton" if key == "card:" + cid else "TButton")
        self._play_enabled()

    def select_play_target(self, event=None):
        index = self.target_combo.current()
        self.selected_target = self.target_ids[index] if index >= 0 else None
        self._play_enabled()

    def _play_enabled(self):
        self.controls["play"].configure(state="normal" if self.selected_card and self.selected_target else "disabled")

    def _render_choices(self, parent, view, token):
        phase = view["phase"]
        ttk.Label(parent, text=PHASE_NAMES[phase], style="Section.TLabel").pack(anchor="w", pady=(2, 10))
        explanations = {"refusal": "领队已公开声明能力；请确认执行或拒绝。这里不能跳过。",
                        "decision": "请完成必要的目标或效果选择。强制效果不能跳过。",
                        "reveal": (f"{view['action_counts']['mastermind'] + view['action_counts']['protagonists']} 张暗牌均已放置。"
                                   "揭示后所有牌及结算结果都会公开。"),
                        "day_start": "准备开始今天的行动。接下来由剧作家放置暗牌。",
                        "day_end": "同时点的强制能力已统一触发并结算。现在可按任意顺序发动可选能力，或结束本阶段。",
                        "loop_end": "当前轮回已失败。主人公可在这里自由讨论，然后重置棋盘继续。"}
        ttk.Label(parent, text=explanations.get(phase, "可以依次使用合法能力，也可以结束本阶段。强制效果由引擎自动结算。"),
                  wraplength=345, style="Muted.TLabel").pack(fill="x", pady=(0, 12))
        options = self.session.options()
        self.option_items = [(c["id"], c) for c in options]
        if self.option_items:
            list_frame = ttk.Frame(parent)
            list_frame.pack(fill="both", expand=True)
            box = tk.Listbox(list_frame, bg=CARD, fg=INK, selectbackground=LINE, selectforeground=ACCENT,
                             borderwidth=0, highlightthickness=0, font=("Microsoft YaHei UI", 10),
                             width=1, height=8, exportselection=False, activestyle="none")
            bar = ttk.Scrollbar(list_frame, orient="vertical", command=box.yview)
            box.configure(yscrollcommand=bar.set)
            box.pack(side="left", fill="both", expand=True)
            bar.pack(side="right", fill="y")
            for number, (_, choice) in enumerate(self.option_items, 1):
                box.insert("end", f"{number}. {choice['label']}")
            self.controls["options"] = box
            self.choice_summary = ttk.Label(parent, text="选择一项，查看完整说明。", wraplength=345, foreground=ACCENT)
            self.choice_summary.pack(fill="x", pady=12)
            box.bind("<<ListboxSelect>>", self.select_option)
            self.controls["choose"] = ttk.Button(parent, text="确认执行所选项", state="disabled", style="Accent.TButton",
                                                  command=lambda: self.perform(token, "choose", action_id=self.selected_option))
            self.controls["choose"].pack(fill="x", pady=(0, 10))
        elif phase in ("master_abilities", "goodwill", "action_counters", "day_end"):
            ttk.Label(parent, text="当前没有可发动的能力。", style="Muted.TLabel").pack(pady=18)
        if phase == "reveal":
            total = view["action_counts"]["mastermind"] + view["action_counts"]["protagonists"]
            self.controls["resolve"] = ttk.Button(parent, text=f"统一揭示 {total} 张牌", command=lambda: self.perform(token, "resolve"), style="Accent.TButton")
            self.controls["resolve"].pack(fill="x", pady=15)
        if phase in NEXT_LABELS:
            self.controls["next"] = ttk.Button(parent, text=NEXT_LABELS[phase], command=lambda: self.perform(token, "next"))
            self.controls["next"].pack(fill="x", pady=(6, 0))
        if phase == "loop_end" and module_capability(view, "early_final_guess"):
            ttk.Button(parent, text="交给领队：提前最终猜测…", command=self.request_final).pack(fill="x", pady=12)

    def select_option(self, event=None):
        selection = self.controls["options"].curselection()
        if selection:
            action_id, item = self.option_items[selection[0]]
            self.selected_option = action_id
            self.choice_summary.configure(text=item["label"])
            self.controls["choose"].configure(state="normal")

    def _render_guess(self, parent, view, token):
        ttk.Label(parent, text="最后的机会", style="Section.TLabel").pack(anchor="w", pady=12)
        ttk.Label(parent, text="按任意顺序猜测每个角色的初始身份。\n全部正确才获胜，答错一次即失败。", wraplength=345, foreground=DANGER).pack(fill="x", pady=10)
        characters = list(view["guess_remaining"])
        roles = list(module_roles(view["module"]))
        ttk.Label(parent, text=f"待猜角色（剩余 {len(characters)} 名）").pack(anchor="w", pady=(14, 5))
        char_box = ttk.Combobox(parent, state="readonly", values=[target_name(view, c) for c in characters])
        char_box.pack(fill="x", pady=5)
        ttk.Label(parent, text="初始身份").pack(anchor="w", pady=(14, 5))
        role_box = ttk.Combobox(parent, state="readonly", values=[ROLE_NAMES[r] for r in roles])
        role_box.pack(fill="x", pady=5)
        self.controls["guess_character"], self.controls["guess_role"] = char_box, role_box
        summary = ttk.Label(parent, text="选择角色与身份后，再确认提交。", wraplength=345, foreground=ACCENT)
        summary.pack(fill="x", pady=16)

        def selected(event=None):
            valid = char_box.current() >= 0 and role_box.current() >= 0
            self.controls["guess"].configure(state="normal" if valid else "disabled")
            if valid:
                summary.configure(text=f"将公开声明：{char_box.get()}是{role_box.get()}。此操作不可撤销。")

        char_box.bind("<<ComboboxSelected>>", selected)
        role_box.bind("<<ComboboxSelected>>", selected)
        self.controls["guess"] = ttk.Button(parent, text="确认提交这次猜测", state="disabled", style="Accent.TButton",
                                            command=lambda: self.perform(token, "guess", character=characters[char_box.current()], role=roles[role_box.current()]))
        self.controls["guess"].pack(fill="x", pady=10)

    def _render_replay_controls(self):
        session = self.session
        self.seat_title.configure(text="完整对局回放")
        self.seat_subtitle.configure(text="只读模式 · 回放包含所有玩家的暗牌和决策，请只在对局结束后观看。")
        navigation = ttk.Frame(self.private)
        navigation.pack(fill="x", pady=(8, 12))
        for label, target in (("⏮ 开始", 0), ("◀ 上一步", session.index - 1),
                              ("下一步 ▶", session.index + 1), ("结尾 ⏭", session.length)):
            ttk.Button(navigation, text=label, command=lambda i=target: self.replay_seek(i),
                       state="normal" if 0 <= target <= session.length and target != session.index else "disabled").pack(
                           side="left", expand=True, fill="x", padx=2)
        current = session.current_decision
        if current is None:
            detail = "初始状态：尚未执行任何玩家决策。"
        else:
            detail = f"第 {current.number} 个决策\n{current.description}"
            if current.steps:
                detail += "\n\n本步结算：\n" + "\n".join("• " + step.message for step in current.steps)
        ttk.Label(self.private, text=detail, wraplength=385, justify="left",
                  foreground=ACCENT).pack(fill="x", pady=(0, 12))
        ttk.Label(self.private, text="全部决策", style="Section.TLabel").pack(anchor="w", pady=(4, 5))
        frame, text = text_panel(self.private, 14)
        frame.pack(fill="both", expand=True)
        lines = []
        for index, record in enumerate(session.decisions, 1):
            marker = "▶" if index == session.index else " "
            lines.append(f"{marker} {index:04d}  {record.description}")
        set_text(text, "\n".join(lines))

    def replay_seek(self, index):
        try:
            self.session.seek(max(0, min(self.session.length, index)))
            self.inspect_target = None
            self._error = ""
            self.public_tabs.select(self.log_frame)
        except ValueError as exc:
            self._error = str(exc)
        self.render()

    def inspect(self, target):
        # Inspecting public cards must not rebuild/erase an in-progress private choice.
        self.inspect_target = target
        view = self.session.public_view()
        self._render_board(view)
        if target in view["characters"]:
            set_text(self.details_text, character_details(view, target))
        else:
            set_text(self.details_text, f"{LOCATIONS[target]}\n\n密谋：{view['locations'][target]}\n\n可以放置行动牌佯攻；只有密谋及其禁止在地点上有效。")
        self.public_tabs.select(self.details_frame)

    def unlock(self, seat):
        try:
            self.session.unlock(seat)
            self._error = ""
        except ValueError as exc:
            self._error = str(exc)
        self.render()

    def hide(self):
        self.session.hide()
        self._error = ""
        self.render()

    def perform(self, token, action, **args):
        try:
            self.session.act(token, action, **args)
            self._error = ""
            self.public_tabs.select(self.log_frame)
        except (ValueError, TypeError) as exc:
            self._error = str(exc)
        self.render()

    def request_final(self):
        try:
            self.session.request_final_guess()
            self._error = ""
        except ValueError as exc:
            self._error = str(exc)
        self.render()

    def cancel_final(self):
        self.session.cancel_final_guess()
        self.render()

    def _focus_out(self, event):
        if self._focus_job:
            self.root.after_cancel(self._focus_job)
        self._focus_job = self.root.after(100, self._check_focus)

    def _check_focus(self):
        self._focus_job = None
        # The Tcl path works for native ttk combobox popdowns as well as Tk widgets.
        if not self.root.tk.call("focus", "-displayof", self.root._w) and self.session.seat is not None:
            self.hide()

    def _unmap(self, event):
        if event.widget == self.root and self.session.seat is not None:
            self.hide()

    def _wheel(self, event):
        widget = event.widget
        while widget is not None:
            if isinstance(widget, (tk.Text, tk.Listbox, ttk.Combobox)):
                return
            if isinstance(widget, ScrollFrame):
                widget.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
                return "break"
            widget = getattr(widget, "master", None)

    def _confirm_replace(self):
        self.hide()
        if not self.session.dirty:
            return True
        answer = messagebox.askyesnocancel("尚未保存", "当前对局有未保存的操作。\n\n是：先另存；否：放弃未保存的操作；取消：返回对局。", parent=self.root)
        return self.save() if answer is True else answer is False

    def new_game(self):
        self.hide()
        popup = tk.Toplevel(self.root)
        popup.title("开始新对局")
        popup.transient(self.root)
        popup.configure(bg=PANEL)
        popup.resizable(False, False)
        frame = ttk.Frame(popup, padding=25)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="选择教学剧本", style="Section.TLabel").pack(anchor="w", pady=(0, 12))
        ttk.Label(frame, text="这是原创教学剧本。所有座位均由真人控制，\n可以一人操作多个座位。", style="Muted.TLabel").pack(anchor="w", pady=(0, 15))

        def start(module):
            popup.destroy()
            if self._confirm_replace():
                self.session = HotseatSession.new(module)
                self.inspect_target = None
                self._error = ""
                self.render()

        for index, (module, spec) in enumerate((item for item in MODULES.items() if item[1].gui_supported)):
            ending = "有最终猜测" if spec.final_guess else "无最终猜测"
            style = "Accent.TButton" if index == 0 else "TButton"
            ttk.Button(frame, text=f"{module} · {spec.name} / {ending}",
                       command=lambda selected=module: start(selected), style=style).pack(fill="x", pady=6)
        ttk.Button(frame, text="取消", command=popup.destroy).pack(fill="x", pady=(14, 0))
        popup.grab_set()

    def open_file(self, scenario):
        self.hide()
        path = filedialog.askopenfilename(parent=self.root, title="载入剧本 JSON" if scenario else "恢复完整对局存档",
                                          filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            loaded = (HotseatSession.from_scenario_file(path) if scenario
                      else HotseatSession.from_save_file(path))
        except (ValueError, TypeError, OSError) as exc:
            messagebox.showerror("无法载入", str(exc), parent=self.root)
            return
        if not self._confirm_replace():
            return
        self.session = loaded
        self.inspect_target = None
        self._error = ""
        self.render()

    def open_replay(self):
        self.hide()
        path = filedialog.askopenfilename(parent=self.root, title="打开完整对局回放",
                                          filetypes=[("悲剧轮回回放", "*.tlr"), ("文本文件", "*.txt"),
                                                     ("所有文件", "*.*")])
        if not path:
            return
        try:
            session = ReplaySession(ReplayArchive.load(path))
        except (ValueError, TypeError, OSError) as exc:
            messagebox.showerror("无法打开回放", str(exc), parent=self.root)
            return
        if not self._confirm_replace():
            return
        self.session = session
        self.inspect_target = None
        self._error = ""
        self.render()

    def save(self):
        if getattr(self.session, "replay_mode", False):
            messagebox.showinfo("只读回放", "回放模式不能另存为可继续操作的对局。", parent=self.root)
            return False
        self.hide()
        path = filedialog.asksaveasfilename(parent=self.root, title="另存对局（包含全部秘密；请选择新文件）",
                                            initialfile="tragedy-session.json", defaultextension=".json",
                                            filetypes=[("JSON 存档", "*.json")], confirmoverwrite=False)
        if not path:
            return False
        try:
            self.session.save(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("未能保存", "请使用一个新的文件名；不会覆盖已有存档。\n\n" + str(exc), parent=self.root)
            return False
        self._error = ""
        self.render()
        self.status.configure(text=f"已保存：{Path(path).name} · 文件含秘密，请勿分享给主人公", foreground=ACCENT)
        return True

    def export_replay(self):
        self.hide()
        if not self.session.finished:
            messagebox.showerror("不能导出回放", "完整对局结束后才能导出纯文本回放。", parent=self.root)
            return False
        path = filedialog.asksaveasfilename(parent=self.root, title="导出完整信息回放（请选择新文件）",
                                            initialfile="tragedy-replay.tlr", defaultextension=".tlr",
                                            filetypes=[("悲剧轮回回放", "*.tlr"), ("文本文件", "*.txt")],
                                            confirmoverwrite=False)
        if not path:
            return False
        try:
            self.session.save_replay(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("未能导出回放", "请使用一个新的文件名；不会覆盖已有文件。\n\n" + str(exc), parent=self.root)
            return False
        self.status.configure(text=f"已导出回放：{Path(path).name} · 文件包含全部秘密", foreground=ACCENT)
        return True

    def close(self):
        if self._confirm_replace():
            if self._focus_job:
                self.root.after_cancel(self._focus_job)
            self.root.destroy()


def _console_error(message):
    stream = sys.stderr or sys.stdout
    if stream is not None:
        print(message, file=stream)


def main(argv=None, *, error_reporter=None):
    error_reporter = error_reporter or _console_error
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = GuiArgumentParser(description="悲剧轮回本地热座 GUI")
    parser.add_argument("--module", choices=tuple(m for m, spec in MODULES.items() if spec.gui_supported), default="FS")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--script", help="载入 JSON 剧本")
    source.add_argument("--load", help="恢复 JSON 存档")
    source.add_argument("--replay", help="打开 .tlr 完整对局回放")
    try:
        args = parser.parse_args(argv)
    except ValueError as exc:
        error_reporter(f"无法解析 GUI 启动参数：{exc}")
        return 2
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        error_reporter(f"无法打开桌面窗口：{exc}\n请在有图形桌面、安装了 Tk 的 Python 环境运行。")
        return 1
    root.withdraw()
    try:
        session = ReplaySession(ReplayArchive.load(args.replay)) if args.replay else None
        game = None
        if session is None:
            session = (HotseatSession.from_save_file(args.load) if args.load else
                       HotseatSession.from_scenario_file(args.script) if args.script else
                       HotseatSession.new(args.module))
    except (ValueError, TypeError, OSError) as exc:
        messagebox.showerror("无法开始对局", str(exc), parent=root)
        root.destroy()
        return 1
    TragedyApp(root, game, session=session)
    root.deiconify()
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
