"""Windows-friendly Tk renderer for Luna's command-center desktop shell."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any, Literal

from .controller import DesktopShellController
from .layout import DesktopLayout, desktop_layout_for_width
from .models import (
    DesktopAccessMode,
    DesktopComposerDraft,
    DesktopSection,
    DesktopShellSnapshot,
    DesktopTaskCard,
    DesktopTaskState,
)
from .theme import (
    BASE_FONT_FAMILY,
    BASE_FONT_SIZE,
    COMPOSER_RADIUS,
    CONTENT_MAX_WIDTH,
    LABEL_FONT_SIZE,
    LUNA_DARK_PALETTE,
    LUNA_LIGHT_PALETTE,
    SMALL_FONT_SIZE,
    TITLE_FONT_SIZE,
    LunaPalette,
)


def _shorten(value: str, limit: int) -> str:
    cleaned = " ".join(value.split())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1].rstrip()}…"


def _state_colors(palette: LunaPalette, state: DesktopTaskState) -> tuple[str, str]:
    if state is DesktopTaskState.VERIFIED_COMPLETE:
        return palette.success, palette.success_soft
    if state in {
        DesktopTaskState.BLOCKED,
        DesktopTaskState.RECOVERY_REQUIRED,
        DesktopTaskState.SUSPENDED,
    }:
        return palette.warning, palette.warning_soft
    if state is DesktopTaskState.FAILED:
        return palette.danger, palette.danger_soft
    if state is DesktopTaskState.WORKING:
        return palette.accent_primary, palette.accent_soft
    return palette.text_secondary, palette.state_hover


def _section_title(section: DesktopSection) -> tuple[str, str]:
    mapping = {
        DesktopSection.CHAT: ("Yeni görev", "Luna ile güvenli bir çalışma başlat"),
        DesktopSection.PROJECTS: ("Projeler", "Etkin çalışma alanı"),
        DesktopSection.TASKS: ("Görevler", "Kalıcı runtime kuyruğu"),
        DesktopSection.RESEARCH: ("Araştırmalar", "Mevcut araştırma durumu"),
        DesktopSection.SCHEDULES: ("Otomasyonlar", "Salt okunur zamanlama görünümü"),
        DesktopSection.SKILLS: ("Skills", "Bağlı yetenek görünümü"),
        DesktopSection.SETTINGS: ("Ayarlar", "Yerel görünüm tercihleri"),
        DesktopSection.NOTIFICATIONS: ("Bildirimler", "Yalnızca yerel bildirimler"),
    }
    return mapping[section]


def launch_desktop_shell(controller: DesktopShellController) -> int:
    """Launch the local shell; runtime authority remains outside the renderer."""
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.title("Luna")
    root.geometry("1440x900")
    root.minsize(720, 580)

    initial_snapshot = controller.snapshot()
    state: dict[str, Any] = {
        "dark": False,
        "section": initial_snapshot.selected_section,
        "active_item_id": None,
        "draft": "",
        "inspector_manual": None,
        "inspector_tab": "CHANGES",
        "layout": desktop_layout_for_width(1440),
        "rebuild_pending": False,
    }
    widgets: dict[str, Any] = {}

    def palette() -> LunaPalette:
        return LUNA_DARK_PALETTE if state["dark"] else LUNA_LIGHT_PALETTE

    def rounded_rectangle(
        canvas: Any,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        radius: int,
        **options: Any,
    ) -> int:
        points = (
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        )
        return int(canvas.create_polygon(points, smooth=True, splinesteps=24, **options))

    def flat_button(
        parent: Any,
        *,
        text: str,
        command: Callable[[], None],
        base_bg: str,
        hover_bg: str,
        foreground: str,
        anchor: Literal["nw", "n", "ne", "w", "center", "e", "sw", "s", "se"] = "w",
        font: tuple[Any, ...] | None = None,
        padx: int = 10,
        pady: int = 7,
        disabled: bool = False,
    ) -> Any:
        current = palette()
        button = tk.Button(
            parent,
            text=text,
            command=command,
            anchor=anchor,
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=base_bg,
            highlightcolor=current.state_focus,
            bg=base_bg,
            activebackground=hover_bg,
            fg=foreground,
            activeforeground=foreground,
            disabledforeground=current.state_disabled,
            font=font or (BASE_FONT_FAMILY, LABEL_FONT_SIZE),
            padx=padx,
            pady=pady,
            cursor="arrow" if disabled else "hand2",
            takefocus=True,
            state=tk.DISABLED if disabled else tk.NORMAL,
        )
        return button

    def surface_card(
        parent: Any,
        *,
        background: str | None = None,
    ) -> tuple[Any, Any]:
        current = palette()
        outer = tk.Frame(parent, bg=current.border_subtle)
        inner = tk.Frame(outer, bg=background or current.bg_elevated)
        inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        return outer, inner

    def create_luna_mark_placeholder(parent: Any, compact: bool) -> Any:
        """Render a replaceable Luna-owned mark placeholder with no external asset."""
        current = palette()
        row = tk.Frame(parent, bg=current.bg_sidebar)
        mark = tk.Canvas(
            row,
            width=30,
            height=30,
            bg=current.bg_sidebar,
            highlightthickness=0,
        )
        rounded_rectangle(
            mark,
            2,
            2,
            28,
            28,
            8,
            fill=current.text_primary,
            outline="",
        )
        mark.create_text(
            15,
            15,
            text="L",
            fill=current.bg_primary,
            font=(BASE_FONT_FAMILY, 11, "bold"),
        )
        mark.pack(side=tk.LEFT)
        if not compact:
            name_wrap = tk.Frame(row, bg=current.bg_sidebar)
            name_wrap.pack(side=tk.LEFT, padx=(10, 0))
            tk.Label(
                name_wrap,
                text="Luna",
                bg=current.bg_sidebar,
                fg=current.text_primary,
                font=(BASE_FONT_FAMILY, 13, "bold"),
                anchor="w",
            ).pack(anchor="w")
            tk.Label(
                name_wrap,
                text="YEREL ÇALIŞMA ALANI",
                bg=current.bg_sidebar,
                fg=current.text_muted,
                font=(BASE_FONT_FAMILY, 7),
                anchor="w",
            ).pack(anchor="w", pady=(1, 0))
        return row

    def active_task(snapshot: DesktopShellSnapshot) -> DesktopTaskCard | None:
        active_id = state["active_item_id"]
        if active_id is not None:
            for task in snapshot.tasks:
                if str(task.item_id) == active_id:
                    return task
        if state["section"] is DesktopSection.TASKS and snapshot.tasks:
            state["active_item_id"] = str(snapshot.tasks[0].item_id)
            return snapshot.tasks[0]
        return None

    def select_section(section: DesktopSection) -> None:
        state["section"] = section
        if section is DesktopSection.CHAT:
            state["active_item_id"] = None
        controller.select_section(section)
        build_shell()

    def select_task(item_id: str) -> None:
        state["active_item_id"] = item_id
        state["section"] = DesktopSection.TASKS
        controller.select_section(DesktopSection.TASKS)
        build_shell()

    def set_theme(dark: bool) -> None:
        if state["dark"] == dark:
            return
        state["dark"] = dark
        build_shell()

    def toggle_theme() -> None:
        set_theme(not bool(state["dark"]))

    def build_sidebar(parent: Any, snapshot: DesktopShellSnapshot) -> None:
        current = palette()
        layout: DesktopLayout = state["layout"]
        compact = layout.compact_navigation
        workspace_name = Path(snapshot.workspace_root).name or snapshot.workspace_root

        mark = create_luna_mark_placeholder(parent, compact)
        mark.pack(
            fill=tk.X,
            padx=20 if not compact else 21,
            pady=(18, 16 if not compact else 12),
        )

        new_task = flat_button(
            parent,
            text="+" if compact else "+  Yeni görev",
            command=partial(select_section, DesktopSection.CHAT),
            base_bg=current.text_primary,
            hover_bg=current.accent_primary,
            foreground=current.bg_primary,
            anchor="center" if compact else "w",
            font=(BASE_FONT_FAMILY, 12 if compact else 10, "bold"),
            padx=8,
            pady=8,
        )
        new_task.pack(fill=tk.X, padx=12, pady=(0, 18))

        if compact:
            compact_nav = (
                ("P", DesktopSection.PROJECTS),
                ("T", DesktopSection.TASKS),
                ("A", DesktopSection.SCHEDULES),
                ("S", DesktopSection.SKILLS),
            )
            for label, section in compact_nav:
                selected = state["section"] is section
                button = flat_button(
                    parent,
                    text=label,
                    command=partial(select_section, section),
                    base_bg=(
                        current.state_selected if selected else current.bg_sidebar
                    ),
                    hover_bg=current.state_hover,
                    foreground=current.text_primary,
                    anchor="center",
                    font=(BASE_FONT_FAMILY, 10, "bold"),
                    padx=4,
                    pady=9,
                )
                button.pack(fill=tk.X, padx=12, pady=2)
            tk.Frame(parent, bg=current.bg_sidebar).pack(fill=tk.BOTH, expand=True)
            settings = flat_button(
                parent,
                text="⚙",
                command=partial(select_section, DesktopSection.SETTINGS),
                base_bg=(
                    current.state_selected
                    if state["section"] is DesktopSection.SETTINGS
                    else current.bg_sidebar
                ),
                hover_bg=current.state_hover,
                foreground=current.text_secondary,
                anchor="center",
                padx=4,
                pady=9,
            )
            settings.pack(fill=tk.X, padx=12, pady=(0, 14))
            return

        tk.Label(
            parent,
            text="ÇALIŞMA ALANI",
            bg=current.bg_sidebar,
            fg=current.text_muted,
            font=(BASE_FONT_FAMILY, 8, "bold"),
            anchor="w",
        ).pack(fill=tk.X, padx=20, pady=(0, 6))

        projects_selected = state["section"] is DesktopSection.PROJECTS
        project_button = flat_button(
            parent,
            text=f"▱  {_shorten(workspace_name, 24)}",
            command=partial(select_section, DesktopSection.PROJECTS),
            base_bg=(current.state_selected if projects_selected else current.bg_sidebar),
            hover_bg=current.state_hover,
            foreground=current.text_primary,
            padx=10,
            pady=7,
        )
        project_button.pack(fill=tk.X, padx=10, pady=(0, 10))

        thread_header = tk.Frame(parent, bg=current.bg_sidebar)
        thread_header.pack(fill=tk.X, padx=20, pady=(4, 6))
        tk.Label(
            thread_header,
            text="THREADS",
            bg=current.bg_sidebar,
            fg=current.text_muted,
            font=(BASE_FONT_FAMILY, 8, "bold"),
        ).pack(side=tk.LEFT)
        tk.Label(
            thread_header,
            text=str(len(snapshot.tasks)),
            bg=current.bg_sidebar,
            fg=current.text_muted,
            font=(BASE_FONT_FAMILY, 8),
        ).pack(side=tk.RIGHT)

        if snapshot.tasks:
            for task in snapshot.tasks[:6]:
                selected = state["active_item_id"] == str(task.item_id)
                task_button = flat_button(
                    parent,
                    text=_shorten(task.title, 30),
                    command=partial(select_task, str(task.item_id)),
                    base_bg=(
                        current.state_selected if selected else current.bg_sidebar
                    ),
                    hover_bg=current.state_hover,
                    foreground=(
                        current.text_primary if selected else current.text_secondary
                    ),
                    font=(BASE_FONT_FAMILY, SMALL_FONT_SIZE),
                    padx=10,
                    pady=6,
                )
                task_button.pack(fill=tk.X, padx=10, pady=1)
        else:
            tk.Label(
                parent,
                text="Henüz görev yok",
                bg=current.bg_sidebar,
                fg=current.text_muted,
                font=(BASE_FONT_FAMILY, SMALL_FONT_SIZE),
                anchor="w",
            ).pack(fill=tk.X, padx=20, pady=(3, 8))

        tk.Frame(parent, bg=current.bg_sidebar).pack(fill=tk.BOTH, expand=True)

        footer_items = (
            ("◷  Otomasyonlar", DesktopSection.SCHEDULES),
            ("◇  Skills", DesktopSection.SKILLS),
            ("⚙  Ayarlar", DesktopSection.SETTINGS),
        )
        for label, section in footer_items:
            selected = state["section"] is section
            footer_button = flat_button(
                parent,
                text=label,
                command=partial(select_section, section),
                base_bg=(current.state_selected if selected else current.bg_sidebar),
                hover_bg=current.state_hover,
                foreground=current.text_secondary,
                font=(BASE_FONT_FAMILY, SMALL_FONT_SIZE),
                padx=10,
                pady=6,
            )
            footer_button.pack(fill=tk.X, padx=10, pady=1)

        local_status = tk.Frame(parent, bg=current.bg_sidebar)
        local_status.pack(fill=tk.X, padx=20, pady=(12, 16))
        tk.Label(
            local_status,
            text="●",
            bg=current.bg_sidebar,
            fg=current.success,
            font=(BASE_FONT_FAMILY, 7),
        ).pack(side=tk.LEFT)
        tk.Label(
            local_status,
            text="  Yerel • salt okunur",
            bg=current.bg_sidebar,
            fg=current.text_muted,
            font=(BASE_FONT_FAMILY, 8),
        ).pack(side=tk.LEFT)

    def page_heading(parent: Any, title: str, description: str) -> Any:
        current = palette()
        block = tk.Frame(parent, bg=current.bg_primary)
        block.pack(fill=tk.X, pady=(2, 22))
        tk.Label(
            block,
            text=title,
            bg=current.bg_primary,
            fg=current.text_primary,
            font=(BASE_FONT_FAMILY, 20, "bold"),
            anchor="w",
        ).pack(fill=tk.X)
        tk.Label(
            block,
            text=description,
            bg=current.bg_primary,
            fg=current.text_secondary,
            font=(BASE_FONT_FAMILY, BASE_FONT_SIZE),
            anchor="w",
        ).pack(fill=tk.X, pady=(6, 0))
        return block

    def render_empty_task(parent: Any, snapshot: DesktopShellSnapshot) -> None:
        current = palette()
        spacer = tk.Frame(parent, bg=current.bg_primary, height=92)
        spacer.pack(fill=tk.X)
        spacer.pack_propagate(False)
        tk.Label(
            parent,
            text=snapshot.shell_message,
            bg=current.bg_primary,
            fg=current.text_primary,
            font=(BASE_FONT_FAMILY, TITLE_FONT_SIZE, "bold"),
        ).pack(pady=(16, 9))
        tk.Label(
            parent,
            text=(
                "Bir hedef tanımla. Luna görevi mevcut çalışma alanında "
                "runtime kuyruğuna iletsin."
            ),
            bg=current.bg_primary,
            fg=current.text_secondary,
            font=(BASE_FONT_FAMILY, BASE_FONT_SIZE),
            wraplength=540,
            justify=tk.CENTER,
        ).pack()
        guard = tk.Frame(parent, bg=current.bg_primary)
        guard.pack(pady=(22, 0))
        for label in ("Salt okunur", "Yerel runtime", "Kanıta bağlı durum"):
            tk.Label(
                guard,
                text=label,
                bg=current.bg_secondary,
                fg=current.text_secondary,
                font=(BASE_FONT_FAMILY, SMALL_FONT_SIZE),
                padx=10,
                pady=5,
            ).pack(side=tk.LEFT, padx=4)

    def render_active_task(parent: Any, task: DesktopTaskCard) -> None:
        current = palette()
        page_heading(parent, "Görev", "Aktif thread ve runtime etkinliği")

        author = tk.Frame(parent, bg=current.bg_primary)
        author.pack(fill=tk.X, pady=(0, 7))
        tk.Label(
            author,
            text="SEN",
            bg=current.bg_primary,
            fg=current.text_muted,
            font=(BASE_FONT_FAMILY, 8, "bold"),
        ).pack(side=tk.LEFT)

        message_outer, message = surface_card(parent, background=current.bg_secondary)
        message_outer.pack(fill=tk.X, pady=(0, 22))
        tk.Label(
            message,
            text=task.title,
            bg=current.bg_secondary,
            fg=current.text_primary,
            font=(BASE_FONT_FAMILY, BASE_FONT_SIZE),
            wraplength=720,
            justify=tk.LEFT,
            anchor="w",
            padx=16,
            pady=14,
        ).pack(fill=tk.X)

        activity_head = tk.Frame(parent, bg=current.bg_primary)
        activity_head.pack(fill=tk.X, pady=(0, 7))
        tk.Label(
            activity_head,
            text="LUNA RUNTIME",
            bg=current.bg_primary,
            fg=current.text_muted,
            font=(BASE_FONT_FAMILY, 8, "bold"),
        ).pack(side=tk.LEFT)

        activity_outer, activity = surface_card(parent)
        activity_outer.pack(fill=tk.X)
        top = tk.Frame(activity, bg=current.bg_elevated)
        top.pack(fill=tk.X, padx=16, pady=(14, 7))
        tk.Label(
            top,
            text="Runtime etkinliği",
            bg=current.bg_elevated,
            fg=current.text_primary,
            font=(BASE_FONT_FAMILY, BASE_FONT_SIZE, "bold"),
        ).pack(side=tk.LEFT)
        state_fg, state_bg = _state_colors(current, task.state)
        tk.Label(
            top,
            text=f"●  {task.state_label}",
            bg=state_bg,
            fg=state_fg,
            font=(BASE_FONT_FAMILY, SMALL_FONT_SIZE, "bold"),
            padx=9,
            pady=4,
        ).pack(side=tk.RIGHT)
        tk.Label(
            activity,
            text=(
                "Görev durumu kalıcı kuyruk ve runtime sonucundan okunur. "
                "Bu görünüm yetki veya tamamlanma üretmez."
            ),
            bg=current.bg_elevated,
            fg=current.text_secondary,
            font=(BASE_FONT_FAMILY, LABEL_FONT_SIZE),
            wraplength=680,
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, padx=16, pady=(0, 13))
        metrics = tk.Frame(activity, bg=current.bg_elevated)
        metrics.pack(fill=tk.X, padx=16, pady=(0, 14))
        for label, value in (
            ("Kanıt", str(task.evidence_count)),
            ("Gözlem", str(task.observation_count)),
            ("Güncel durum", task.state_label),
        ):
            metric = tk.Frame(metrics, bg=current.bg_secondary)
            metric.pack(side=tk.LEFT, padx=(0, 7))
            tk.Label(
                metric,
                text=label,
                bg=current.bg_secondary,
                fg=current.text_muted,
                font=(BASE_FONT_FAMILY, 8),
                padx=9,
                pady=3,
            ).pack(anchor="w")
            tk.Label(
                metric,
                text=value,
                bg=current.bg_secondary,
                fg=current.text_primary,
                font=(BASE_FONT_FAMILY, SMALL_FONT_SIZE, "bold"),
                padx=9,
                pady=3,
            ).pack(anchor="w")

    def render_projects(parent: Any, snapshot: DesktopShellSnapshot) -> None:
        current = palette()
        page_heading(parent, "Projeler", "Luna'nın bağlı olduğu çalışma alanı")
        project_outer, project = surface_card(parent)
        project_outer.pack(fill=tk.X)
        title_row = tk.Frame(project, bg=current.bg_elevated)
        title_row.pack(fill=tk.X, padx=16, pady=(15, 5))
        tk.Label(
            title_row,
            text=Path(snapshot.workspace_root).name or snapshot.workspace_root,
            bg=current.bg_elevated,
            fg=current.text_primary,
            font=(BASE_FONT_FAMILY, 12, "bold"),
        ).pack(side=tk.LEFT)
        tk.Label(
            title_row,
            text="ETKİN",
            bg=current.success_soft,
            fg=current.success,
            font=(BASE_FONT_FAMILY, 8, "bold"),
            padx=8,
            pady=3,
        ).pack(side=tk.RIGHT)
        tk.Label(
            project,
            text=snapshot.workspace_root,
            bg=current.bg_elevated,
            fg=current.text_secondary,
            font=(BASE_FONT_FAMILY, SMALL_FONT_SIZE),
            anchor="w",
        ).pack(fill=tk.X, padx=16)
        tk.Label(
            project,
            text=f"{len(snapshot.tasks)} thread  •  Varsayılan erişim: salt okunur",
            bg=current.bg_elevated,
            fg=current.text_muted,
            font=(BASE_FONT_FAMILY, SMALL_FONT_SIZE),
            anchor="w",
        ).pack(fill=tk.X, padx=16, pady=(10, 15))

    def render_automations(parent: Any, snapshot: DesktopShellSnapshot) -> None:
        current = palette()
        page_heading(
            parent,
            "Otomasyonlar",
            "Mevcut zamanlama kayıtlarının salt okunur görünümü",
        )
        if not snapshot.schedules:
            outer, empty = surface_card(parent, background=current.bg_secondary)
            outer.pack(fill=tk.X)
            tk.Label(
                empty,
                text="Zamanlanmış otomasyon yok",
                bg=current.bg_secondary,
                fg=current.text_primary,
                font=(BASE_FONT_FAMILY, BASE_FONT_SIZE, "bold"),
                anchor="w",
            ).pack(fill=tk.X, padx=16, pady=(15, 5))
            tk.Label(
                empty,
                text=(
                    "Bu ilk kabuk yeni bir zamanlayıcı oluşturmaz; yalnızca runtime'ın "
                    "mevcut kayıtlarını gösterir."
                ),
                bg=current.bg_secondary,
                fg=current.text_secondary,
                font=(BASE_FONT_FAMILY, LABEL_FONT_SIZE),
                wraplength=650,
                justify=tk.LEFT,
                anchor="w",
            ).pack(fill=tk.X, padx=16, pady=(0, 15))
            return
        for schedule in snapshot.schedules:
            outer, card = surface_card(parent)
            outer.pack(fill=tk.X, pady=(0, 8))
            tk.Label(
                card,
                text=schedule.title,
                bg=current.bg_elevated,
                fg=current.text_primary,
                font=(BASE_FONT_FAMILY, LABEL_FONT_SIZE, "bold"),
                anchor="w",
            ).pack(fill=tk.X, padx=14, pady=(12, 4))
            tk.Label(
                card,
                text=f"{schedule.kind}  •  {schedule.next_run_at.isoformat()}",
                bg=current.bg_elevated,
                fg=current.text_muted,
                font=(BASE_FONT_FAMILY, SMALL_FONT_SIZE),
                anchor="w",
            ).pack(fill=tk.X, padx=14, pady=(0, 12))

    def render_skills(parent: Any) -> None:
        current = palette()
        page_heading(parent, "Skills", "Luna'nın bağlı yetenekleri için görünüm kabuğu")
        outer, empty = surface_card(parent, background=current.bg_secondary)
        outer.pack(fill=tk.X)
        tk.Label(
            empty,
            text="Bağlı skill kataloğu sunulmadı",
            bg=current.bg_secondary,
            fg=current.text_primary,
            font=(BASE_FONT_FAMILY, BASE_FONT_SIZE, "bold"),
            anchor="w",
        ).pack(fill=tk.X, padx=16, pady=(15, 5))
        tk.Label(
            empty,
            text=(
                "Bu görünüm bir skill çalıştırmaz ve yeni runtime yetkisi vermez. "
                "Mevcut bir katalog bağlandığında içerik burada gösterilebilir."
            ),
            bg=current.bg_secondary,
            fg=current.text_secondary,
            font=(BASE_FONT_FAMILY, LABEL_FONT_SIZE),
            wraplength=650,
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, padx=16, pady=(0, 15))

    def render_settings(parent: Any) -> None:
        current = palette()
        page_heading(parent, "Ayarlar", "Yerel ve yalnızca görsel tercihler")
        outer, card = surface_card(parent)
        outer.pack(fill=tk.X)
        tk.Label(
            card,
            text="Görünüm",
            bg=current.bg_elevated,
            fg=current.text_primary,
            font=(BASE_FONT_FAMILY, BASE_FONT_SIZE, "bold"),
            anchor="w",
        ).pack(fill=tk.X, padx=16, pady=(15, 4))
        tk.Label(
            card,
            text="Tema seçimi yalnızca masaüstü sunumunu değiştirir.",
            bg=current.bg_elevated,
            fg=current.text_secondary,
            font=(BASE_FONT_FAMILY, LABEL_FONT_SIZE),
            anchor="w",
        ).pack(fill=tk.X, padx=16)
        choices = tk.Frame(card, bg=current.bg_elevated)
        choices.pack(fill=tk.X, padx=16, pady=(14, 16))
        for label, dark in (("Açık", False), ("Koyu", True)):
            selected = bool(state["dark"]) is dark
            choice = flat_button(
                choices,
                text=label,
                command=partial(set_theme, dark),
                base_bg=(
                    current.accent_soft if selected else current.bg_secondary
                ),
                hover_bg=current.state_hover,
                foreground=(
                    current.accent_primary if selected else current.text_secondary
                ),
                anchor="center",
                font=(BASE_FONT_FAMILY, LABEL_FONT_SIZE, "bold"),
                padx=20,
                pady=8,
            )
            choice.pack(side=tk.LEFT, padx=(0, 8))

    def render_notifications(parent: Any, snapshot: DesktopShellSnapshot) -> None:
        current = palette()
        page_heading(parent, "Bildirimler", "Yalnızca yerel outbox kayıtları")
        if not snapshot.notifications:
            tk.Label(
                parent,
                text="Bekleyen yerel bildirim yok",
                bg=current.bg_primary,
                fg=current.text_muted,
                font=(BASE_FONT_FAMILY, BASE_FONT_SIZE),
                anchor="w",
            ).pack(fill=tk.X)
            return
        for notification in snapshot.notifications:
            outer, card = surface_card(parent)
            outer.pack(fill=tk.X, pady=(0, 8))
            tk.Label(
                card,
                text=notification.message,
                bg=current.bg_elevated,
                fg=current.text_primary,
                font=(BASE_FONT_FAMILY, LABEL_FONT_SIZE),
                anchor="w",
                wraplength=680,
                justify=tk.LEFT,
            ).pack(fill=tk.X, padx=14, pady=12)

    def render_content() -> None:
        inner = widgets["content_inner"]
        for child in inner.winfo_children():
            child.destroy()
        snapshot = controller.snapshot()
        task = active_task(snapshot)
        section: DesktopSection = state["section"]
        title, subtitle = _section_title(section)
        if task is not None and section is DesktopSection.TASKS:
            title = _shorten(task.title, 64)
            subtitle = f"{task.state_label}  •  Runtime kuyruğu"
        widgets["header_title"].set(title)
        widgets["header_subtitle"].set(subtitle)

        column = tk.Frame(inner, bg=palette().bg_primary)
        column.pack(fill=tk.X, padx=36, pady=(28, 54))
        if section is DesktopSection.CHAT:
            render_empty_task(column, snapshot)
        elif section is DesktopSection.PROJECTS:
            render_projects(column, snapshot)
        elif section is DesktopSection.TASKS:
            if task is None:
                render_empty_task(column, snapshot)
            else:
                render_active_task(column, task)
        elif section is DesktopSection.SCHEDULES:
            render_automations(column, snapshot)
        elif section is DesktopSection.SKILLS:
            render_skills(column)
        elif section is DesktopSection.SETTINGS:
            render_settings(column)
        elif section is DesktopSection.NOTIFICATIONS:
            render_notifications(column, snapshot)
        else:
            page_heading(column, "Araştırmalar", "Mevcut veri bu kabukta sunulmadı")
        inner.update_idletasks()
        widgets["content_canvas"].configure(
            scrollregion=widgets["content_canvas"].bbox("all")
        )

    def render_inspector() -> None:
        current = palette()
        body = widgets["inspector_body"]
        for child in body.winfo_children():
            child.destroy()
        snapshot = controller.snapshot()
        task = active_task(snapshot)
        tab = state["inspector_tab"]

        if task is None:
            tk.Label(
                body,
                text="Çalışma alanı",
                bg=current.bg_inspector,
                fg=current.text_primary,
                font=(BASE_FONT_FAMILY, LABEL_FONT_SIZE, "bold"),
                anchor="w",
            ).pack(fill=tk.X, padx=16, pady=(18, 5))
            tk.Label(
                body,
                text=snapshot.workspace_root,
                bg=current.bg_inspector,
                fg=current.text_secondary,
                font=(BASE_FONT_FAMILY, SMALL_FONT_SIZE),
                wraplength=260,
                justify=tk.LEFT,
                anchor="w",
            ).pack(fill=tk.X, padx=16)
        elif tab == "CHANGES":
            tk.Label(
                body,
                text="Değişiklik verisi yok",
                bg=current.bg_inspector,
                fg=current.text_primary,
                font=(BASE_FONT_FAMILY, LABEL_FONT_SIZE, "bold"),
                anchor="w",
            ).pack(fill=tk.X, padx=16, pady=(18, 5))
            tk.Label(
                body,
                text=(
                    "Runtime anlık görüntüsü bu görev için dosya diff'i sunmuyor. "
                    "Dosya değişikliği, doğrulama olarak yorumlanmaz."
                ),
                bg=current.bg_inspector,
                fg=current.text_secondary,
                font=(BASE_FONT_FAMILY, SMALL_FONT_SIZE),
                wraplength=270,
                justify=tk.LEFT,
                anchor="w",
            ).pack(fill=tk.X, padx=16)
        elif tab == "EVIDENCE":
            tk.Label(
                body,
                text="Kanıt özeti",
                bg=current.bg_inspector,
                fg=current.text_primary,
                font=(BASE_FONT_FAMILY, LABEL_FONT_SIZE, "bold"),
                anchor="w",
            ).pack(fill=tk.X, padx=16, pady=(18, 10))
            for label, value in (
                ("Kanıt kaydı", str(task.evidence_count)),
                ("Runtime gözlemi", str(task.observation_count)),
            ):
                row = tk.Frame(body, bg=current.bg_inspector)
                row.pack(fill=tk.X, padx=16, pady=4)
                tk.Label(
                    row,
                    text=label,
                    bg=current.bg_inspector,
                    fg=current.text_secondary,
                    font=(BASE_FONT_FAMILY, SMALL_FONT_SIZE),
                ).pack(side=tk.LEFT)
                tk.Label(
                    row,
                    text=value,
                    bg=current.bg_inspector,
                    fg=current.text_primary,
                    font=(BASE_FONT_FAMILY, SMALL_FONT_SIZE, "bold"),
                ).pack(side=tk.RIGHT)
            if task.unresolved_uncertainty:
                tk.Label(
                    body,
                    text="Çözümlenmemiş belirsizlik",
                    bg=current.bg_inspector,
                    fg=current.warning,
                    font=(BASE_FONT_FAMILY, SMALL_FONT_SIZE, "bold"),
                    anchor="w",
                ).pack(fill=tk.X, padx=16, pady=(14, 4))
                for uncertainty in task.unresolved_uncertainty:
                    tk.Label(
                        body,
                        text=f"• {uncertainty}",
                        bg=current.bg_inspector,
                        fg=current.text_secondary,
                        font=(BASE_FONT_FAMILY, SMALL_FONT_SIZE),
                        wraplength=265,
                        justify=tk.LEFT,
                        anchor="w",
                    ).pack(fill=tk.X, padx=16, pady=2)
        else:
            verified = task.state is DesktopTaskState.VERIFIED_COMPLETE
            title = "Doğrulandı" if verified else "Henüz doğrulanmadı"
            title_color = current.success if verified else current.text_primary
            tk.Label(
                body,
                text=title,
                bg=current.bg_inspector,
                fg=title_color,
                font=(BASE_FONT_FAMILY, LABEL_FONT_SIZE, "bold"),
                anchor="w",
            ).pack(fill=tk.X, padx=16, pady=(18, 5))
            tk.Label(
                body,
                text=(
                    "Bu sonuç runtime kanıtına bağlıdır."
                    if verified
                    else "Görev durumu tek başına doğrulanmış tamamlanma anlamına gelmez."
                ),
                bg=current.bg_inspector,
                fg=current.text_secondary,
                font=(BASE_FONT_FAMILY, SMALL_FONT_SIZE),
                wraplength=270,
                justify=tk.LEFT,
                anchor="w",
            ).pack(fill=tk.X, padx=16)
            verification_rows = (
                ("Completion", task.completion_status or "—"),
                ("Verification report", str(task.verification_report_id or "—")),
                ("Final report", str(task.final_report_id or "—")),
            )
            for label, value in verification_rows:
                tk.Label(
                    body,
                    text=label.upper(),
                    bg=current.bg_inspector,
                    fg=current.text_muted,
                    font=(BASE_FONT_FAMILY, 7, "bold"),
                    anchor="w",
                ).pack(fill=tk.X, padx=16, pady=(14, 3))
                tk.Label(
                    body,
                    text=value,
                    bg=current.bg_inspector,
                    fg=current.text_secondary,
                    font=(BASE_FONT_FAMILY, 8),
                    wraplength=268,
                    justify=tk.LEFT,
                    anchor="w",
                ).pack(fill=tk.X, padx=16)

        divider = tk.Frame(body, bg=current.border_subtle, height=1)
        divider.pack(fill=tk.X, padx=16, pady=(22, 14))
        tk.Label(
            body,
            text="RUNTIME KAYNAKLARI",
            bg=current.bg_inspector,
            fg=current.text_muted,
            font=(BASE_FONT_FAMILY, 8, "bold"),
            anchor="w",
        ).pack(fill=tk.X, padx=16, pady=(0, 7))
        resource_text = (
            f"Worker {snapshot.resources.worker_slots_held}  •  "
            f"Model {snapshot.resources.model_slots_held}  •  "
            f"Network {snapshot.resources.network_slots_held}"
        )
        tk.Label(
            body,
            text=resource_text,
            bg=current.bg_inspector,
            fg=current.text_secondary,
            font=(BASE_FONT_FAMILY, SMALL_FONT_SIZE),
            anchor="w",
        ).pack(fill=tk.X, padx=16)
        if task is not None:
            tk.Label(
                body,
                text="TASK ID",
                bg=current.bg_inspector,
                fg=current.text_muted,
                font=(BASE_FONT_FAMILY, 7, "bold"),
                anchor="w",
            ).pack(fill=tk.X, padx=16, pady=(18, 3))
            tk.Label(
                body,
                text=str(task.task_id),
                bg=current.bg_inspector,
                fg=current.text_secondary,
                font=(BASE_FONT_FAMILY, 8),
                wraplength=268,
                justify=tk.LEFT,
                anchor="w",
            ).pack(fill=tk.X, padx=16)

    def choose_inspector_tab(tab: str) -> None:
        state["inspector_tab"] = tab
        build_shell()

    def toggle_inspector() -> None:
        inspector_shell = widgets["inspector_shell"]
        currently_visible = bool(inspector_shell.winfo_manager())
        state["inspector_manual"] = not currently_visible
        apply_layout(root.winfo_width())

    def build_inspector(parent: Any) -> None:
        current = palette()
        header = tk.Frame(parent, bg=current.bg_inspector, height=60)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(
            header,
            text="Bağlam",
            bg=current.bg_inspector,
            fg=current.text_primary,
            font=(BASE_FONT_FAMILY, BASE_FONT_SIZE, "bold"),
        ).pack(side=tk.LEFT, padx=16)
        close = flat_button(
            header,
            text="x",
            command=toggle_inspector,
            base_bg=current.bg_inspector,
            hover_bg=current.state_hover,
            foreground=current.text_secondary,
            anchor="center",
            font=(BASE_FONT_FAMILY, 13),
            padx=8,
            pady=3,
        )
        close.pack(side=tk.RIGHT, padx=9)

        tabs = tk.Frame(parent, bg=current.bg_inspector)
        tabs.pack(fill=tk.X, padx=12, pady=(0, 4))
        for tab, label in (
            ("CHANGES", "Değişiklikler"),
            ("EVIDENCE", "Kanıt"),
            ("VERIFICATION", "Doğrulama"),
        ):
            selected = state["inspector_tab"] == tab
            button = flat_button(
                tabs,
                text=label,
                command=partial(choose_inspector_tab, tab),
                base_bg=(
                    current.state_selected if selected else current.bg_inspector
                ),
                hover_bg=current.state_hover,
                foreground=(
                    current.text_primary if selected else current.text_muted
                ),
                anchor="center",
                font=(BASE_FONT_FAMILY, 8, "bold" if selected else "normal"),
                padx=6,
                pady=6,
            )
            button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=1)
        tk.Frame(parent, bg=current.border_subtle, height=1).pack(fill=tk.X)
        body = tk.Frame(parent, bg=current.bg_inspector)
        body.pack(fill=tk.BOTH, expand=True)
        widgets["inspector_body"] = body

    def send() -> None:
        composer = widgets.get("composer")
        if composer is None:
            return
        text = composer.get("1.0", tk.END).strip()
        if not text:
            return
        try:
            item_id = controller.submit(
                DesktopComposerDraft(
                    text=text,
                    workspace_root=controller.workspace_root,
                    access_mode=DesktopAccessMode.READ_ONLY,
                )
            )
        except Exception as exc:
            messagebox.showerror("Luna", str(exc))
            return
        state["draft"] = ""
        state["active_item_id"] = item_id
        state["section"] = DesktopSection.TASKS
        controller.select_section(DesktopSection.TASKS)
        build_shell()

    def update_composer_state(*_args: Any) -> None:
        composer = widgets.get("composer")
        placeholder = widgets.get("composer_placeholder")
        send_button = widgets.get("send_button")
        if composer is None or placeholder is None or send_button is None:
            return
        has_text = bool(composer.get("1.0", tk.END).strip())
        if has_text:
            placeholder.place_forget()
            send_button.configure(
                state=tk.NORMAL,
                cursor="hand2",
                bg=palette().text_primary,
                fg=palette().bg_primary,
            )
        else:
            placeholder.place(x=8, y=7)
            send_button.configure(
                state=tk.DISABLED,
                cursor="arrow",
                bg=palette().state_hover,
                fg=palette().state_disabled,
            )

    def build_composer(parent: Any, snapshot: DesktopShellSnapshot) -> None:
        current = palette()
        wrapper = tk.Frame(parent, bg=current.bg_primary)
        wrapper.pack(side=tk.BOTTOM, fill=tk.X, padx=28, pady=(8, 20))
        canvas = tk.Canvas(
            wrapper,
            height=126,
            bg=current.bg_primary,
            highlightthickness=0,
        )
        canvas.pack(fill=tk.X)
        surface = tk.Frame(canvas, bg=current.bg_elevated)
        surface_window = canvas.create_window(16, 13, anchor="nw", window=surface)

        composer = tk.Text(
            surface,
            height=3,
            bg=current.bg_elevated,
            fg=current.text_primary,
            insertbackground=current.text_primary,
            selectbackground=current.accent_soft,
            selectforeground=current.text_primary,
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0,
            font=(BASE_FONT_FAMILY, BASE_FONT_SIZE),
            padx=8,
            pady=6,
            wrap=tk.WORD,
            undo=True,
        )
        composer.pack(fill=tk.BOTH, expand=True)
        if state["draft"]:
            composer.insert("1.0", state["draft"])
        placeholder = tk.Label(
            composer,
            text="Luna'ya bir görev ver…",
            bg=current.bg_elevated,
            fg=current.text_muted,
            font=(BASE_FONT_FAMILY, BASE_FONT_SIZE),
            cursor="xterm",
        )
        placeholder.bind("<Button-1>", lambda _event: composer.focus_set())

        context = tk.Frame(surface, bg=current.bg_elevated)
        context.pack(fill=tk.X, padx=6, pady=(0, 3))
        workspace_name = Path(snapshot.workspace_root).name or snapshot.workspace_root
        for label in (
            _shorten(workspace_name, 22),
            "Salt okunur",
            "Runtime kuyruğu",
        ):
            tk.Label(
                context,
                text=label,
                bg=current.bg_secondary,
                fg=current.text_secondary,
                font=(BASE_FONT_FAMILY, 8),
                padx=8,
                pady=4,
            ).pack(side=tk.LEFT, padx=(0, 5))
        send_button = flat_button(
            context,
            text="↑",
            command=send,
            base_bg=current.state_hover,
            hover_bg=current.accent_hover,
            foreground=current.state_disabled,
            anchor="center",
            font=(BASE_FONT_FAMILY, 12, "bold"),
            padx=10,
            pady=3,
            disabled=True,
        )
        send_button.pack(side=tk.RIGHT)

        def draw_composer(event: Any) -> None:
            canvas.delete("composer_surface")
            rounded_rectangle(
                canvas,
                2,
                2,
                max(event.width - 2, 4),
                124,
                COMPOSER_RADIUS,
                fill=current.bg_elevated,
                outline=current.border_strong,
                width=1,
                tags="composer_surface",
            )
            canvas.tag_lower("composer_surface")
            canvas.itemconfigure(
                surface_window,
                width=max(event.width - 32, 1),
                height=100,
            )

        canvas.bind("<Configure>", draw_composer)
        composer.bind("<KeyRelease>", update_composer_state)
        composer.bind("<FocusIn>", update_composer_state)
        composer.bind("<FocusOut>", update_composer_state)
        widgets["composer"] = composer
        widgets["composer_placeholder"] = placeholder
        widgets["send_button"] = send_button
        root.after_idle(update_composer_state)

    def build_main(parent: Any, snapshot: DesktopShellSnapshot) -> None:
        current = palette()
        header = tk.Frame(parent, bg=current.bg_primary, height=64)
        header.pack(side=tk.TOP, fill=tk.X)
        header.pack_propagate(False)
        titles = tk.Frame(header, bg=current.bg_primary)
        titles.pack(side=tk.LEFT, fill=tk.Y, padx=24)
        title, subtitle = _section_title(state["section"])
        title_var = tk.StringVar(value=title)
        subtitle_var = tk.StringVar(value=subtitle)
        tk.Label(
            titles,
            textvariable=title_var,
            bg=current.bg_primary,
            fg=current.text_primary,
            font=(BASE_FONT_FAMILY, LABEL_FONT_SIZE, "bold"),
            anchor="w",
        ).pack(anchor="w", pady=(12, 1))
        tk.Label(
            titles,
            textvariable=subtitle_var,
            bg=current.bg_primary,
            fg=current.text_muted,
            font=(BASE_FONT_FAMILY, 8),
            anchor="w",
        ).pack(anchor="w")
        widgets["header_title"] = title_var
        widgets["header_subtitle"] = subtitle_var

        theme_button = flat_button(
            header,
            text="☀" if state["dark"] else "☾",
            command=toggle_theme,
            base_bg=current.bg_primary,
            hover_bg=current.state_hover,
            foreground=current.text_secondary,
            anchor="center",
            font=(BASE_FONT_FAMILY, 11),
            padx=9,
            pady=5,
        )
        theme_button.pack(side=tk.RIGHT, padx=(0, 12), pady=14)
        inspector_button = flat_button(
            header,
            text="Bağlam",
            command=toggle_inspector,
            base_bg=current.bg_primary,
            hover_bg=current.state_hover,
            foreground=current.text_secondary,
            anchor="center",
            font=(BASE_FONT_FAMILY, SMALL_FONT_SIZE),
            padx=10,
            pady=5,
        )
        inspector_button.pack(side=tk.RIGHT, padx=(0, 5), pady=14)
        tk.Frame(parent, bg=current.border_subtle, height=1).pack(side=tk.TOP, fill=tk.X)

        if state["section"] in {DesktopSection.CHAT, DesktopSection.TASKS}:
            build_composer(parent, snapshot)

        canvas = tk.Canvas(
            parent,
            bg=current.bg_primary,
            highlightthickness=0,
            borderwidth=0,
        )
        canvas.pack(fill=tk.BOTH, expand=True)
        inner = tk.Frame(canvas, bg=current.bg_primary)
        window = canvas.create_window(0, 0, anchor="nw", window=inner)

        def sync_scroll_region(_event: Any) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def sync_content_width(event: Any) -> None:
            usable = max(event.width, 1)
            content_width = min(usable, CONTENT_MAX_WIDTH)
            left = max((usable - content_width) // 2, 0)
            canvas.coords(window, left, 0)
            canvas.itemconfigure(window, width=content_width)

        inner.bind("<Configure>", sync_scroll_region)
        canvas.bind("<Configure>", sync_content_width)
        widgets["content_canvas"] = canvas
        widgets["content_inner"] = inner

    def build_shell() -> None:
        composer = widgets.get("composer")
        if composer is not None and composer.winfo_exists():
            state["draft"] = composer.get("1.0", tk.END).strip()
        for child in root.winfo_children():
            child.destroy()
        widgets.clear()
        current = palette()
        root.configure(bg=current.bg_primary)
        snapshot = controller.snapshot()

        sidebar = tk.Frame(root, bg=current.bg_sidebar, width=state["layout"].sidebar_width)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)
        divider = tk.Frame(root, bg=current.border_subtle, width=1)
        divider.pack(side=tk.LEFT, fill=tk.Y)
        stage = tk.Frame(root, bg=current.bg_primary)
        stage.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        main = tk.Frame(stage, bg=current.bg_primary)
        main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        inspector_shell = tk.Frame(stage, bg=current.bg_inspector)
        inspector_divider = tk.Frame(inspector_shell, bg=current.border_subtle, width=1)
        inspector_divider.pack(side=tk.LEFT, fill=tk.Y)
        inspector = tk.Frame(
            inspector_shell,
            bg=current.bg_inspector,
            width=state["layout"].inspector_width,
        )
        inspector.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        inspector.pack_propagate(False)
        widgets.update(
            {
                "sidebar": sidebar,
                "stage": stage,
                "main": main,
                "inspector_shell": inspector_shell,
                "inspector": inspector,
            }
        )

        build_sidebar(sidebar, snapshot)
        build_main(main, snapshot)
        build_inspector(inspector)
        render_content()
        render_inspector()
        root.update_idletasks()
        apply_layout(root.winfo_width())

    def schedule_rebuild() -> None:
        if state["rebuild_pending"]:
            return
        state["rebuild_pending"] = True

        def rebuild() -> None:
            state["rebuild_pending"] = False
            build_shell()

        root.after_idle(rebuild)

    def apply_layout(width: int) -> None:
        layout = desktop_layout_for_width(width)
        previous: DesktopLayout = state["layout"]
        state["layout"] = layout
        if layout.mode is not previous.mode:
            schedule_rebuild()
            return
        sidebar = widgets.get("sidebar")
        inspector = widgets.get("inspector")
        inspector_shell = widgets.get("inspector_shell")
        main = widgets.get("main")
        if sidebar is None or inspector is None or inspector_shell is None or main is None:
            return
        sidebar.configure(width=layout.sidebar_width)
        inspector.configure(width=layout.inspector_width)
        manual = state["inspector_manual"]
        should_show = layout.inspector_default_visible if manual is None else bool(manual)
        if should_show:
            if not inspector_shell.winfo_manager():
                inspector_shell.pack(side=tk.RIGHT, fill=tk.Y, before=main)
        else:
            inspector_shell.pack_forget()

    def on_root_resize(event: Any) -> None:
        if event.widget is root:
            apply_layout(event.width)

    def scroll_content(event: Any) -> str | None:
        canvas = widgets.get("content_canvas")
        if canvas is None:
            return None
        canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    root.bind("<Configure>", on_root_resize)
    root.bind("<MouseWheel>", scroll_content)
    root.bind("<Control-Return>", lambda _event: send())
    build_shell()
    root.mainloop()
    return 0
