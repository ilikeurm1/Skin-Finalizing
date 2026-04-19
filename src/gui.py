from __future__ import annotations

import base64
import logging
import math
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .utils.catalog import CatalogResolver
from .utils.constants import (
    CT_CLASS_ID,
    GUI_DARK_ACCENT,
    GUI_DARK_BG,
    GUI_DARK_BORDER,
    GUI_DARK_CARD,
    GUI_DARK_MUTED,
    GUI_DARK_PANEL,
    GUI_DARK_TEXT,
    STEAM_IMAGE_CDN_HOST,
    T_CLASS_ID,
)
from .utils.models import InventoryItem, LoadoutChoice
from .utils.runtime import CenteredLevelFormatter, LOGGER
from .utils.text import truncate_text


class GuiUnavailableError(RuntimeError):
    pass


class SelectionCanceledError(RuntimeError):
    pass


class GuiLogHandler(logging.Handler):
    def __init__(self, emit_line: Callable[[str], None]) -> None:
        super().__init__(level=logging.INFO)
        self.emit_line = emit_line

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.emit_line(self.format(record))
        except Exception:
            self.handleError(record)


def side_name_for_class(class_id: str) -> str:
    return "T Side" if class_id == T_CLASS_ID else "CT Side"


def build_image_fetch_urls(url: str) -> list[str]:
    if not url:
        return []

    candidates = [url]
    try:
        parsed = urlsplit(url)
    except ValueError:
        return candidates

    host = parsed.netloc.lower()
    if parsed.path.startswith("/economy/image/") and host != STEAM_IMAGE_CDN_HOST:
        if host.endswith(".steamstatic.com") or host.endswith(".steamstatic.com:443"):
            LOGGER.debug(
                "Normalizing Steam image host from %s to %s",
                parsed.netloc,
                STEAM_IMAGE_CDN_HOST,
            )
            candidates.insert(
                0,
                urlunsplit(parsed._replace(netloc=STEAM_IMAGE_CDN_HOST)),
            )

    unique_candidates: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        unique_candidates.append(candidate)
        seen.add(candidate)
    return unique_candidates


class GuiImageCache:
    def __init__(self, tk_module: Any) -> None:
        self.tk = tk_module
        self.raw_cache: dict[str, bytes] = {}
        self.photo_cache: dict[tuple[str, int, int], Any] = {}

    def get(self, url: str, max_width: int, max_height: int) -> Any | None:
        if not url:
            return None

        cache_key = (url, max_width, max_height)
        if cache_key in self.photo_cache:
            LOGGER.debug("Using cached GUI image for %s", url)
            return self.photo_cache[cache_key]

        raw = self.raw_cache.get(url)
        if raw is None:
            for candidate_url in build_image_fetch_urls(url):
                raw = self.raw_cache.get(candidate_url)
                if raw is None:
                    LOGGER.debug("Fetching GUI image from %s", candidate_url)
                    request = Request(
                        candidate_url,
                        headers={"User-Agent": "csgo-gc-skin-finalizer/1.0"},
                    )
                    try:
                        with urlopen(request, timeout=10) as response:
                            raw = response.read()
                    except (HTTPError, URLError, TimeoutError, OSError) as exc:
                        LOGGER.debug(
                            "Failed to fetch GUI image from %s: %s",
                            candidate_url,
                            exc,
                        )
                        raw = None
                        continue
                    self.raw_cache[candidate_url] = raw

                self.raw_cache[url] = raw
                break

        if raw is None:
            LOGGER.warning("Preview unavailable for %s", url)
            return None

        try:
            image = self.tk.PhotoImage(data=base64.b64encode(raw).decode("ascii"))
        except self.tk.TclError as exc:
            LOGGER.warning("Failed to decode preview image for %s: %s", url, exc)
            return None

        width = max(1, image.width())
        height = max(1, image.height())
        scale = max(1, math.ceil(width / max_width), math.ceil(height / max_height))
        if scale > 1:
            image = image.subsample(scale, scale)

        self.photo_cache[cache_key] = image
        return image


class LoadoutSelectionGui:
    def __init__(
        self,
        tk_module: Any,
        ttk_module: Any,
        all_choices: list[LoadoutChoice],
        initial_selected_by_pair: dict[tuple[str, str], InventoryItem],
        ambiguous_choices: list[LoadoutChoice],
        resolver: CatalogResolver,
    ) -> None:
        self.tk = tk_module
        self.ttk = ttk_module
        self.resolver = resolver
        self.all_choices = all_choices
        self.ambiguous_choices = ambiguous_choices
        self.selected_by_pair = dict(initial_selected_by_pair)
        self.current_by_pair = {choice.pair: choice.current for choice in all_choices}
        self.choice_by_pair = {choice.pair: choice for choice in all_choices}
        self.side_pairs = {
            T_CLASS_ID: [
                choice.pair for choice in all_choices if choice.pair[0] == T_CLASS_ID
            ],
            CT_CLASS_ID: [
                choice.pair for choice in all_choices if choice.pair[0] == CT_CLASS_ID
            ],
        }
        self.side_prompt_counts = {
            T_CLASS_ID: len(
                [choice for choice in ambiguous_choices if choice.pair[0] == T_CLASS_ID]
            ),
            CT_CLASS_ID: len(
                [
                    choice
                    for choice in ambiguous_choices
                    if choice.pair[0] == CT_CLASS_ID
                ]
            ),
        }
        self.choice_index = 0
        self.result: dict[tuple[str, str], InventoryItem] | None = None
        self.gui_log_handler: GuiLogHandler | None = None
        self.image_cache = GuiImageCache(tk_module)
        self.root = self.tk.Tk()
        self.root.title("csgo_gc Loadout Selector")
        self.root.geometry("1780x1080")
        self.root.minsize(1260, 760)
        self.root.protocol("WM_DELETE_WINDOW", self.cancel)
        self.root.configure(bg=GUI_DARK_BG)

        style = self.ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except self.tk.TclError:
            pass
        self._configure_theme(style)

        self.title_var = self.tk.StringVar()
        self.subtitle_var = self.tk.StringVar()
        self.status_var = self.tk.StringVar(
            value="Choose the item to equip for each slot."
        )
        self.preview_title_var = self.tk.StringVar()
        self.preview_details_var = self.tk.StringVar()
        self._build_layout()
        self._install_mousewheel_support()
        self._attach_gui_logging()
        LOGGER.info(
            "Loadout selector GUI initialized for %d ambiguous choices",
            len(self.ambiguous_choices),
        )

    def _configure_theme(self, style: Any) -> None:
        style.configure(".", background=GUI_DARK_BG, foreground=GUI_DARK_TEXT)
        style.configure("TFrame", background=GUI_DARK_BG)
        style.configure(
            "TLabelframe",
            background=GUI_DARK_BG,
            foreground=GUI_DARK_TEXT,
            bordercolor=GUI_DARK_BORDER,
            relief="solid",
        )
        style.configure(
            "TLabelframe.Label",
            background=GUI_DARK_BG,
            foreground=GUI_DARK_TEXT,
        )
        style.configure("TLabel", background=GUI_DARK_BG, foreground=GUI_DARK_TEXT)
        style.configure(
            "TButton",
            background=GUI_DARK_PANEL,
            foreground=GUI_DARK_TEXT,
            bordercolor=GUI_DARK_BORDER,
            lightcolor=GUI_DARK_BORDER,
            darkcolor=GUI_DARK_BORDER,
            focusthickness=1,
            focuscolor=GUI_DARK_ACCENT,
            padding=(10, 6),
        )
        style.map(
            "TButton",
            background=[("active", GUI_DARK_CARD), ("pressed", GUI_DARK_ACCENT)],
            foreground=[("disabled", GUI_DARK_MUTED)],
        )
        style.configure(
            "Treeview",
            background=GUI_DARK_PANEL,
            foreground=GUI_DARK_TEXT,
            fieldbackground=GUI_DARK_PANEL,
            bordercolor=GUI_DARK_BORDER,
            rowheight=24,
        )
        style.map(
            "Treeview",
            background=[("selected", GUI_DARK_ACCENT)],
            foreground=[("selected", GUI_DARK_TEXT)],
        )
        style.configure(
            "Treeview.Heading",
            background=GUI_DARK_CARD,
            foreground=GUI_DARK_TEXT,
            bordercolor=GUI_DARK_BORDER,
            relief="flat",
        )
        style.map("Treeview.Heading", background=[("active", GUI_DARK_PANEL)])
        style.configure(
            "Vertical.TScrollbar",
            background=GUI_DARK_PANEL,
            troughcolor=GUI_DARK_BG,
            bordercolor=GUI_DARK_BORDER,
            arrowcolor=GUI_DARK_TEXT,
        )

    def _build_layout(self) -> None:
        main_frame = self.ttk.Frame(self.root, padding=12)
        main_frame.pack(fill="both", expand=True)

        header_frame = self.ttk.Frame(main_frame)
        header_frame.pack(fill="x", pady=(0, 12))
        self.ttk.Label(
            header_frame, textvariable=self.title_var, font=("Segoe UI", 16, "bold")
        ).pack(anchor="w")
        self.ttk.Label(header_frame, textvariable=self.subtitle_var).pack(
            anchor="w", pady=(4, 0)
        )

        body_frame = self.ttk.Frame(main_frame)
        body_frame.pack(fill="both", expand=True)

        left_frame = self.ttk.Frame(body_frame)
        left_frame.pack(side="left", fill="y")
        right_frame = self.ttk.Frame(body_frame)
        right_frame.pack(side="left", fill="both", expand=True, padx=(12, 0))

        self.preview_frame = self.ttk.LabelFrame(
            left_frame, text="Selected Preview", padding=8
        )
        self.preview_frame.pack(fill="x")
        self.preview_image_label = self.tk.Label(
            self.preview_frame,
            text="Preview unavailable",
            anchor="center",
            justify="center",
            width=36,
            bg=GUI_DARK_PANEL,
            fg=GUI_DARK_MUTED,
            relief="flat",
            padx=8,
            pady=8,
        )
        self.preview_image_label.pack(fill="x")
        self.ttk.Label(
            self.preview_frame,
            textvariable=self.preview_title_var,
            font=("Segoe UI", 11, "bold"),
            wraplength=340,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))
        self.ttk.Label(
            self.preview_frame,
            textvariable=self.preview_details_var,
            wraplength=340,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        self.loadout_frame = self.ttk.LabelFrame(
            left_frame, text="Current Side Loadout", padding=8
        )
        self.loadout_frame.pack(fill="both", expand=True, pady=(12, 0))
        tree_frame = self.ttk.Frame(self.loadout_frame)
        tree_frame.pack(fill="both", expand=True)
        self.side_tree = self.ttk.Treeview(
            tree_frame,
            columns=("slot", "selection"),
            show="headings",
            height=20,
        )
        self.side_tree.heading("slot", text="Slot")
        self.side_tree.heading("selection", text="Selected")
        self.side_tree.column("slot", width=150, stretch=False)
        self.side_tree.column("selection", width=250, stretch=True)
        tree_scrollbar = self.ttk.Scrollbar(
            tree_frame, orient="vertical", command=self.side_tree.yview
        )
        self.side_tree.configure(yscrollcommand=tree_scrollbar.set)
        self.side_tree.pack(side="left", fill="both", expand=True)
        tree_scrollbar.pack(side="left", fill="y")

        self.options_frame = self.ttk.LabelFrame(right_frame, text="Options", padding=8)
        self.options_frame.pack(fill="both", expand=True)
        self.options_canvas = self.tk.Canvas(
            self.options_frame,
            highlightthickness=0,
            bg=GUI_DARK_BG,
            bd=0,
        )
        options_scrollbar = self.ttk.Scrollbar(
            self.options_frame, orient="vertical", command=self.options_canvas.yview
        )
        self.options_inner = self.ttk.Frame(self.options_canvas)
        self.options_window = self.options_canvas.create_window(
            (0, 0), window=self.options_inner, anchor="nw"
        )
        self.options_inner.bind("<Configure>", self._sync_option_scrollregion)
        self.options_canvas.bind("<Configure>", self._resize_option_window)
        self.options_canvas.configure(yscrollcommand=options_scrollbar.set)
        self.options_canvas.pack(side="left", fill="both", expand=True)
        options_scrollbar.pack(side="left", fill="y")

        controls_frame = self.ttk.Frame(main_frame)
        controls_frame.pack(fill="x", pady=(12, 0))
        self.back_button = self.ttk.Button(
            controls_frame, text="Back", command=self.go_back
        )
        self.back_button.pack(side="left")
        self.keep_button = self.ttk.Button(
            controls_frame, text="Preserve Existing", command=self.preserve_existing
        )
        self.keep_button.pack(side="left", padx=(8, 0))
        self.default_button = self.ttk.Button(
            controls_frame, text="Use Suggested", command=self.use_default
        )
        self.default_button.pack(side="left", padx=(8, 0))
        self.next_button = self.ttk.Button(
            controls_frame, text="Next", command=self.go_next
        )
        self.next_button.pack(side="right")
        self.cancel_button = self.ttk.Button(
            controls_frame, text="Cancel", command=self.cancel
        )
        self.cancel_button.pack(side="right", padx=(0, 8))

        self.ttk.Label(main_frame, textvariable=self.status_var).pack(
            fill="x", pady=(8, 0)
        )

        self.log_frame = self.ttk.LabelFrame(main_frame, text="Log", padding=8)
        self.log_frame.pack(fill="both", pady=(12, 0))
        log_container = self.ttk.Frame(self.log_frame)
        log_container.pack(fill="both", expand=True)
        self.log_text = self.tk.Text(
            log_container,
            height=8,
            wrap="word",
            state="disabled",
            bg=GUI_DARK_PANEL,
            fg=GUI_DARK_TEXT,
            insertbackground=GUI_DARK_TEXT,
            selectbackground=GUI_DARK_ACCENT,
            selectforeground=GUI_DARK_TEXT,
            highlightbackground=GUI_DARK_BORDER,
            highlightcolor=GUI_DARK_ACCENT,
            relief="flat",
            padx=8,
            pady=8,
        )
        log_scrollbar = self.ttk.Scrollbar(
            log_container, orient="vertical", command=self.log_text.yview
        )
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scrollbar.pack(side="left", fill="y")

    def _attach_gui_logging(self) -> None:
        self.gui_log_handler = GuiLogHandler(self.append_log_line)
        self.gui_log_handler.setFormatter(
            CenteredLevelFormatter(
                "%(asctime)s | %(levelname)s | %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        LOGGER.addHandler(self.gui_log_handler)
        self.append_log_line("GUI log attached.")

    def _detach_gui_logging(self) -> None:
        if self.gui_log_handler is None:
            return
        LOGGER.removeHandler(self.gui_log_handler)
        self.gui_log_handler.close()
        self.gui_log_handler = None

    def append_log_line(self, message: str) -> None:
        def _append() -> None:
            if not self.log_text.winfo_exists():
                return
            self.log_text.configure(state="normal")
            self.log_text.insert("end", message + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

        try:
            self.root.after(0, _append)
        except self.tk.TclError:
            return

    def _install_mousewheel_support(self) -> None:
        self.root.bind_all("<MouseWheel>", self._on_options_mousewheel, add="+")
        self.root.bind_all("<Button-4>", self._on_options_mousewheel, add="+")
        self.root.bind_all("<Button-5>", self._on_options_mousewheel, add="+")

    def _widget_is_descendant(self, widget: Any, ancestor: Any) -> bool:
        current = widget
        while current is not None:
            if current is ancestor:
                return True
            parent_name = current.winfo_parent()
            if not parent_name:
                return False
            current = current.nametowidget(parent_name)
        return False

    def _on_options_mousewheel(self, event: Any) -> str | None:
        if not self._widget_is_descendant(event.widget, self.options_canvas):
            return None

        if getattr(event, "delta", 0):
            units = -int(event.delta / 120)
            if units == 0:
                units = -1 if event.delta > 0 else 1
        elif getattr(event, "num", None) == 4:
            units = -1
        else:
            units = 1

        self.options_canvas.yview_scroll(units, "units")
        return "break"

    def _close(self, result: dict[tuple[str, str], InventoryItem] | None) -> None:
        self.result = result
        self._detach_gui_logging()
        self.root.destroy()

    def _sync_option_scrollregion(self, _event: Any | None = None) -> None:
        self.options_canvas.configure(scrollregion=self.options_canvas.bbox("all"))

    def _resize_option_window(self, event: Any) -> None:
        self.options_canvas.itemconfigure(self.options_window, width=event.width)

    def run(self) -> dict[tuple[str, str], InventoryItem]:
        if not self.ambiguous_choices:
            LOGGER.info("No ambiguous choices require GUI interaction")
            return self._ordered_result()

        self.refresh_view()
        self.root.mainloop()
        if self.result is None:
            raise SelectionCanceledError("Loadout selection canceled.")
        return self.result

    def refresh_view(self) -> None:
        choice = self.ambiguous_choices[self.choice_index]
        side_class_id = choice.pair[0]
        side_name = side_name_for_class(side_class_id)
        side_step = 1 + sum(
            1
            for earlier in self.ambiguous_choices[: self.choice_index]
            if earlier.pair[0] == side_class_id
        )
        side_total = self.side_prompt_counts[side_class_id]
        self.title_var.set(f"{side_name}: {choice.label}")
        self.subtitle_var.set(
            f"Selection {self.choice_index + 1} of {len(self.ambiguous_choices)} | "
            f"{side_name} step {side_step} of {side_total}"
        )
        self.loadout_frame.configure(text=f"{side_name} Loadout")
        self.options_frame.configure(text=f"Options for {choice.label}")
        self.keep_button.configure(
            text=(
                "Preserve Existing"
                if choice.current is not None
                else "Leave Unassigned"
            )
        )
        self.next_button.configure(
            text=(
                "Finish"
                if self.choice_index == len(self.ambiguous_choices) - 1
                else "Next"
            )
        )
        self.back_button.configure(
            state="normal" if self.choice_index > 0 else "disabled"
        )
        LOGGER.info("Showing %s", self.title_var.get())
        self.populate_side_tree(side_class_id, choice.pair)
        self.render_option_cards(choice)
        self.refresh_preview(choice)
        self.options_canvas.yview_moveto(0)

    def populate_side_tree(
        self, side_class_id: str, active_pair: tuple[str, str]
    ) -> None:
        for row_id in self.side_tree.get_children():
            self.side_tree.delete(row_id)

        for pair in self.side_pairs.get(side_class_id, []):
            row_id = self.pair_row_id(pair)
            self.side_tree.insert(
                "",
                "end",
                iid=row_id,
                values=(self.choice_by_pair[pair].label, self.side_summary_text(pair)),
            )

        self.side_tree.selection_set(self.pair_row_id(active_pair))
        self.side_tree.focus(self.pair_row_id(active_pair))

    def render_option_cards(self, choice: LoadoutChoice) -> None:
        for child in self.options_inner.winfo_children():
            child.destroy()

        LOGGER.debug(
            "Rendering %d option cards for %s",
            len(choice.candidates),
            choice.label,
        )

        info_text = "Click a card to choose it. Use Preserve Existing to keep the current slot as-is."
        self.ttk.Label(self.options_inner, text=info_text, wraplength=820).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 12)
        )

        self.options_inner.grid_columnconfigure(0, weight=1)
        self.options_inner.grid_columnconfigure(1, weight=1)

        selected_item = self.selected_by_pair.get(choice.pair)
        for index, candidate in enumerate(choice.candidates):
            row = (index // 2) + 1
            column = index % 2
            is_selected = selected_item is candidate
            is_current = choice.current is candidate
            is_suggested = choice.current is None and choice.default_item is candidate

            border_color = "#2b6cb0" if is_selected else "#b0b0b0"
            border_width = 3 if is_selected else 1
            card = self.tk.Frame(
                self.options_inner,
                bg=GUI_DARK_CARD,
                highlightbackground=border_color,
                highlightthickness=border_width,
                bd=0,
                padx=10,
                pady=10,
                cursor="hand2",
            )
            card.grid(row=row, column=column, sticky="nsew", padx=8, pady=8)

            image = self.image_cache.get(
                self.resolver.get_item_image_url(candidate),
                max_width=220,
                max_height=160,
            )
            image_label = self.tk.Label(card, bg=GUI_DARK_CARD, fg=GUI_DARK_MUTED)
            if image is None:
                image_label.configure(text="Preview unavailable", width=28, height=10)
            else:
                image_label.configure(image=image)
                image_label.image = image
            image_label.pack(fill="x")

            title_label = self.tk.Label(
                card,
                text=self.resolver.describe_item_name(candidate),
                wraplength=240,
                justify="left",
                font=("Segoe UI", 10, "bold"),
                bg=GUI_DARK_CARD,
                fg=GUI_DARK_TEXT,
                anchor="w",
            )
            title_label.pack(anchor="w", pady=(10, 0), fill="x")

            detail_lines: list[str] = []
            details = self.resolver.describe_item_details(candidate)
            if details:
                detail_lines.append(details)
            if is_current:
                detail_lines.append("Currently equipped")
            elif is_suggested:
                detail_lines.append("Suggested default")
            if is_selected:
                detail_lines.append("Selected")

            details_label = self.tk.Label(
                card,
                text="\n".join(detail_lines) if detail_lines else "No extra details",
                wraplength=240,
                justify="left",
                bg=GUI_DARK_CARD,
                fg=GUI_DARK_MUTED,
                anchor="w",
            )
            details_label.pack(anchor="w", pady=(6, 0), fill="x")

            for clickable in (card, image_label, title_label, details_label):
                clickable.bind(
                    "<Button-1>",
                    lambda _event, pair=choice.pair, candidate=candidate: self.select_candidate(
                        pair, candidate
                    ),
                )

            self.ttk.Button(
                card,
                text="Selected" if is_selected else "Choose",
                command=lambda candidate=candidate: self.select_candidate(
                    choice.pair, candidate
                ),
            ).pack(anchor="e", pady=(10, 0))

    def refresh_preview(self, choice: LoadoutChoice) -> None:
        active_item = self.selected_by_pair.get(choice.pair)
        if active_item is None:
            active_item = choice.current

        if active_item is None:
            self.preview_image_label.configure(image="", text="No item selected")
            self.preview_image_label.image = None
            self.preview_title_var.set(choice.label)
            self.preview_details_var.set(
                "This slot will keep its current state and remain unassigned."
            )
            return

        image = self.image_cache.get(
            self.resolver.get_item_image_url(active_item), max_width=320, max_height=240
        )
        if image is None:
            self.preview_image_label.configure(image="", text="Preview unavailable")
            self.preview_image_label.image = None
        else:
            self.preview_image_label.configure(image=image, text="")
            self.preview_image_label.image = image

        preview_state = "Selected for equip"
        if choice.current is active_item:
            preview_state = "Currently equipped"
        elif choice.pair not in self.selected_by_pair:
            preview_state = "Preserving current state"

        details = self.resolver.describe_item_details(active_item)
        self.preview_title_var.set(self.resolver.describe_item_name(active_item))
        self.preview_details_var.set(
            preview_state if not details else f"{preview_state} | {details}"
        )

    def side_summary_text(self, pair: tuple[str, str]) -> str:
        selected = self.selected_by_pair.get(pair)
        if selected is not None:
            return truncate_text(self.resolver.describe_item_name(selected))

        current = self.current_by_pair.get(pair)
        if current is not None:
            return truncate_text(
                f"Preserve: {self.resolver.describe_item_name(current)}"
            )
        return "Leave unchanged"

    def pair_row_id(self, pair: tuple[str, str]) -> str:
        return f"{pair[0]}:{pair[1]}"

    def select_candidate(self, pair: tuple[str, str], candidate: InventoryItem) -> None:
        self.selected_by_pair[pair] = candidate
        LOGGER.info(
            "%s set to %s",
            self.choice_by_pair[pair].label,
            self.resolver.describe_item_name(candidate),
        )
        self.status_var.set(
            f"{self.choice_by_pair[pair].label} set to {self.resolver.describe_item_name(candidate)}."
        )
        if self.ambiguous_choices[self.choice_index].pair == pair:
            self.go_next()
            return
        self.refresh_view()

    def preserve_existing(self) -> None:
        choice = self.ambiguous_choices[self.choice_index]
        self.selected_by_pair.pop(choice.pair, None)
        if choice.current is None:
            self.status_var.set(f"{choice.label} will stay unassigned.")
            LOGGER.info("%s will stay unassigned", choice.label)
        else:
            self.status_var.set(
                f"{choice.label} will preserve {self.resolver.describe_item_name(choice.current)}."
            )
            LOGGER.info(
                "%s will preserve %s",
                choice.label,
                self.resolver.describe_item_name(choice.current),
            )
        self.refresh_view()

    def use_default(self) -> None:
        choice = self.ambiguous_choices[self.choice_index]
        self.selected_by_pair[choice.pair] = choice.default_item
        LOGGER.info(
            "%s reset to suggested item %s",
            choice.label,
            self.resolver.describe_item_name(choice.default_item),
        )
        self.status_var.set(
            f"{choice.label} reset to {self.resolver.describe_item_name(choice.default_item)}."
        )
        self.refresh_view()

    def go_back(self) -> None:
        if self.choice_index == 0:
            return
        self.choice_index -= 1
        LOGGER.info("Moved back to previous choice")
        self.refresh_view()

    def go_next(self) -> None:
        if self.choice_index >= len(self.ambiguous_choices) - 1:
            LOGGER.info("Final GUI selection confirmed")
            self._close(self._ordered_result())
            return
        self.choice_index += 1
        LOGGER.info("Advancing to next choice")
        self.refresh_view()

    def cancel(self) -> None:
        LOGGER.warning("Loadout selection canceled by user")
        self._close(None)

    def _ordered_result(self) -> dict[tuple[str, str], InventoryItem]:
        ordered: dict[tuple[str, str], InventoryItem] = {}
        for choice in self.all_choices:
            selected = self.selected_by_pair.get(choice.pair)
            if selected is not None:
                ordered[choice.pair] = selected
        return ordered


def prompt_for_choices_gui(
    all_choices: list[LoadoutChoice],
    initial_selected_by_pair: dict[tuple[str, str], InventoryItem],
    ambiguous_choices: list[LoadoutChoice],
    resolver: CatalogResolver,
) -> dict[tuple[str, str], InventoryItem]:
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError as exc:
        raise GuiUnavailableError("tkinter is not available") from exc

    try:
        LOGGER.info("Launching Tkinter loadout selector")
        gui = LoadoutSelectionGui(
            tk_module=tk,
            ttk_module=ttk,
            all_choices=all_choices,
            initial_selected_by_pair=initial_selected_by_pair,
            ambiguous_choices=ambiguous_choices,
            resolver=resolver,
        )
    except tk.TclError as exc:
        raise GuiUnavailableError(str(exc)) from exc

    return gui.run()
