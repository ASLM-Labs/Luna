"""Minimal Windows-friendly Tk renderer for the Phase 16 Luna desktop shell."""

from __future__ import annotations

from collections.abc import Callable

from .controller import DesktopShellController
from .models import (
    DesktopAccessMode,
    DesktopComposerDraft,
    DesktopSection,
    DesktopTaskCard,
    DesktopTaskState,
)
from .theme import (
    BASE_FONT_FAMILY,
    LUNA_BLUE,
    LUNA_BORDER,
    LUNA_CANVAS,
    LUNA_DANGER,
    LUNA_SECONDARY,
    LUNA_SIDEBAR,
    LUNA_SUCCESS,
    LUNA_SURFACE,
    LUNA_TEXT,
    LUNA_WARNING,
    SIDEBAR_WIDTH,
    TITLE_FONT_SIZE,
)


def launch_desktop_shell(controller: DesktopShellController) -> int:
    """Launch the local shell. Tk is imported lazily so headless tests stay deterministic."""
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.title("Luna")
    root.geometry("1280x820")
    root.minsize(980, 640)
    root.configure(bg=LUNA_SIDEBAR)

    sidebar = tk.Frame(root, bg=LUNA_SIDEBAR, width=SIDEBAR_WIDTH)
    sidebar.pack(side=tk.LEFT, fill=tk.Y)
    sidebar.pack_propagate(False)

    main = tk.Frame(root, bg=LUNA_CANVAS, highlightthickness=1, highlightbackground=LUNA_BORDER)
    main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 12), pady=(12, 12))

    tk.Label(
        sidebar,
        text="Luna",
        bg=LUNA_SIDEBAR,
        fg=LUNA_TEXT,
        font=(BASE_FONT_FAMILY, 16, "bold"),
        anchor="w",
    ).pack(fill=tk.X, padx=18, pady=(20, 14))

    nav_frame = tk.Frame(sidebar, bg=LUNA_SIDEBAR)
    nav_frame.pack(fill=tk.X, padx=10)

    section_title = tk.StringVar(value="Sohbet")
    status_text = tk.StringVar(value="Salt okunur • Runtime üzerinden")

    def nav_button(label: str, section: str) -> None:
        def select() -> None:
            section_title.set(label)
            controller.select_section(DesktopSection(section))
            refresh()

        button = tk.Button(
            nav_frame,
            text=label,
            command=select,
            anchor="w",
            relief=tk.FLAT,
            borderwidth=0,
            bg=LUNA_SIDEBAR,
            activebackground=LUNA_SURFACE,
            fg=LUNA_TEXT,
            font=(BASE_FONT_FAMILY, 10),
            padx=10,
            pady=8,
            cursor="hand2",
        )
        button.pack(fill=tk.X, pady=1)

    nav_button("+  Yeni sohbet", "CHAT")
    nav_button("Görevler", "TASKS")
    nav_button("Araştırmalar", "RESEARCH")
    nav_button("Zamanlananlar", "SCHEDULES")
    nav_button("Bildirimler", "NOTIFICATIONS")

    tk.Label(
        sidebar,
        text="Çalışma alanı",
        bg=LUNA_SIDEBAR,
        fg=LUNA_SECONDARY,
        font=(BASE_FONT_FAMILY, 9),
        anchor="w",
    ).pack(fill=tk.X, padx=18, pady=(28, 6))

    workspace_label = tk.Label(
        sidebar,
        text=controller.workspace_root,
        bg=LUNA_SIDEBAR,
        fg=LUNA_TEXT,
        font=(BASE_FONT_FAMILY, 9),
        anchor="w",
        wraplength=SIDEBAR_WIDTH - 36,
        justify=tk.LEFT,
    )
    workspace_label.pack(fill=tk.X, padx=18)

    header = tk.Frame(main, bg=LUNA_CANVAS)
    header.pack(fill=tk.X, padx=28, pady=(24, 10))
    tk.Label(
        header,
        textvariable=section_title,
        bg=LUNA_CANVAS,
        fg=LUNA_TEXT,
        font=(BASE_FONT_FAMILY, 13, "bold"),
    ).pack(side=tk.LEFT)

    detail_var = tk.StringVar(value="Ayrıntılar")
    details_visible = {"value": False}

    body = tk.Frame(main, bg=LUNA_CANVAS)
    body.pack(fill=tk.BOTH, expand=True, padx=28)

    content = tk.Frame(body, bg=LUNA_CANVAS)
    content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    details = tk.Frame(
        body,
        bg=LUNA_SURFACE,
        width=300,
        highlightthickness=1,
        highlightbackground=LUNA_BORDER,
    )
    details.pack_propagate(False)

    details_text = tk.Text(
        details,
        bg=LUNA_SURFACE,
        fg=LUNA_TEXT,
        relief=tk.FLAT,
        borderwidth=0,
        font=(BASE_FONT_FAMILY, 9),
        wrap=tk.WORD,
        padx=14,
        pady=14,
        state=tk.DISABLED,
    )
    details_text.pack(fill=tk.BOTH, expand=True)

    def toggle_details() -> None:
        if details_visible["value"]:
            details.pack_forget()
            details_visible["value"] = False
            detail_var.set("Ayrıntılar")
        else:
            details.pack(side=tk.RIGHT, fill=tk.Y, padx=(16, 0))
            details_visible["value"] = True
            detail_var.set("Kapat")

    tk.Button(
        header,
        textvariable=detail_var,
        command=toggle_details,
        relief=tk.FLAT,
        borderwidth=0,
        bg=LUNA_CANVAS,
        activebackground=LUNA_SURFACE,
        fg=LUNA_SECONDARY,
        cursor="hand2",
    ).pack(side=tk.RIGHT)

    welcome = tk.Label(
        content,
        text="Luna ile ne geliştirelim?",
        bg=LUNA_CANVAS,
        fg=LUNA_TEXT,
        font=(BASE_FONT_FAMILY, TITLE_FONT_SIZE),
    )
    welcome.pack(pady=(110, 26))

    cards = tk.Frame(content, bg=LUNA_CANVAS)
    cards.pack(fill=tk.BOTH, expand=True)

    composer_wrap = tk.Frame(main, bg=LUNA_CANVAS)
    composer_wrap.pack(fill=tk.X, padx=28, pady=(12, 24))

    tk.Label(
        composer_wrap,
        textvariable=status_text,
        bg=LUNA_CANVAS,
        fg=LUNA_SECONDARY,
        font=(BASE_FONT_FAMILY, 9),
        anchor="w",
    ).pack(fill=tk.X, padx=8, pady=(0, 6))

    composer = tk.Text(
        composer_wrap,
        height=4,
        bg=LUNA_CANVAS,
        fg=LUNA_TEXT,
        insertbackground=LUNA_TEXT,
        relief=tk.FLAT,
        borderwidth=0,
        highlightthickness=1,
        highlightbackground=LUNA_BORDER,
        highlightcolor=LUNA_BLUE,
        font=(BASE_FONT_FAMILY, 11),
        padx=14,
        pady=12,
        wrap=tk.WORD,
    )
    composer.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def tone_color(state: DesktopTaskState) -> str:
        if state is DesktopTaskState.VERIFIED_COMPLETE:
            return LUNA_SUCCESS
        if state in {
            DesktopTaskState.BLOCKED,
            DesktopTaskState.RECOVERY_REQUIRED,
            DesktopTaskState.SUSPENDED,
        }:
            return LUNA_WARNING
        if state is DesktopTaskState.FAILED:
            return LUNA_DANGER
        if state is DesktopTaskState.WORKING:
            return LUNA_BLUE
        return LUNA_SECONDARY

    def fill_details(lines: list[str]) -> None:
        details_text.configure(state=tk.NORMAL)
        details_text.delete("1.0", tk.END)
        details_text.insert("1.0", "\n".join(lines))
        details_text.configure(state=tk.DISABLED)

    def render_card(title: str, state_label: str, color: str, on_open: Callable[[], None]) -> None:
        frame = tk.Frame(
            cards,
            bg=LUNA_SURFACE,
            highlightthickness=1,
            highlightbackground=LUNA_BORDER,
        )
        frame.pack(fill=tk.X, pady=6)
        tk.Label(
            frame,
            text=title,
            bg=LUNA_SURFACE,
            fg=LUNA_TEXT,
            font=(BASE_FONT_FAMILY, 10, "bold"),
            anchor="w",
            wraplength=650,
            justify=tk.LEFT,
        ).pack(fill=tk.X, padx=14, pady=(11, 3))
        row = tk.Frame(frame, bg=LUNA_SURFACE)
        row.pack(fill=tk.X, padx=14, pady=(0, 10))
        tk.Label(
            row,
            text=f"●  {state_label}",
            bg=LUNA_SURFACE,
            fg=color,
            font=(BASE_FONT_FAMILY, 9),
        ).pack(side=tk.LEFT)
        tk.Button(
            row,
            text="Ayrıntıları göster",
            command=on_open,
            relief=tk.FLAT,
            borderwidth=0,
            bg=LUNA_SURFACE,
            activebackground=LUNA_SURFACE,
            fg=LUNA_SECONDARY,
            cursor="hand2",
        ).pack(side=tk.RIGHT)

    def refresh() -> None:
        for child in cards.winfo_children():
            child.destroy()
        snapshot = controller.snapshot()
        if snapshot.tasks:
            welcome.pack_configure(pady=(20, 18))
        else:
            welcome.pack_configure(pady=(110, 26))

        for task in snapshot.tasks[:12]:
            def open_task(task_card: DesktopTaskCard = task) -> None:
                fill_details(
                    [
                        "Görev",
                        task_card.title,
                        "",
                        f"Durum: {task_card.state_label}",
                        f"Task ID: {task_card.task_id}",
                        f"Stop reason: {task_card.stop_reason or '-'}",
                        f"Completion: {task_card.completion_status or '-'}",
                        f"Evidence: {task_card.evidence_count}",
                        f"Observations: {task_card.observation_count}",
                        f"Verification report: {task_card.verification_report_id or '-'}",
                        f"Final report: {task_card.final_report_id or '-'}",
                    ]
                )
                if not details_visible["value"]:
                    toggle_details()

            render_card(
                task.title,
                task.state_label,
                tone_color(task.state),
                open_task,
            )

        status_text.set(
            "Salt okunur • Runtime üzerinden"
            f"   |   {len(snapshot.tasks)} görev"
            f"   |   {len(snapshot.notifications)} bildirim"
        )

    def send() -> None:
        text = composer.get("1.0", tk.END).strip()
        if not text:
            return
        try:
            draft = DesktopComposerDraft(
                text=text,
                workspace_root=controller.workspace_root,
                access_mode=DesktopAccessMode.READ_ONLY,
            )
            controller.submit(draft)
        except Exception as exc:
            messagebox.showerror("Luna", str(exc))
            return
        composer.delete("1.0", tk.END)
        refresh()

    send_button = tk.Button(
        composer_wrap,
        text="↑",
        command=send,
        bg=LUNA_TEXT,
        activebackground=LUNA_TEXT,
        fg=LUNA_CANVAS,
        activeforeground=LUNA_CANVAS,
        relief=tk.FLAT,
        borderwidth=0,
        font=(BASE_FONT_FAMILY, 14, "bold"),
        width=3,
        cursor="hand2",
    )
    send_button.pack(side=tk.LEFT, padx=(8, 0), fill=tk.Y)

    root.bind("<Control-Return>", lambda _event: send())
    refresh()
    root.mainloop()
    return 0
