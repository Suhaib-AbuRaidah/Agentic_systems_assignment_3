"""Bundled presentation assets; no dependency on the source Template folder."""
from pathlib import Path

import gradio as gr

ASSETS = Path(__file__).resolve().parent / "assets"


def asset_text(name):
    return (ASSETS / name).read_text(encoding="utf-8")


def ui_launch_options():
    """Gradio 6 accepts CSS and themes at launch, including notebook launches."""
    theme = gr.themes.Base(
        primary_hue="rose", secondary_hue="stone", neutral_hue="stone",
        font=["Arial", "sans-serif"], font_mono=["Consolas", "monospace"],
        radius_size="sm",
    ).set(
        body_background_fill="#f6f1e7", body_background_fill_dark="#1a1814",
        body_text_color="#1f1a14", body_text_color_dark="#ece3d2",
        body_text_color_subdued="#5a4f42", body_text_color_subdued_dark="#b3a88f",
        background_fill_primary="#fffdf8", background_fill_primary_dark="#28241d",
        background_fill_secondary="#efe8da", background_fill_secondary_dark="#1d1a14",
        block_background_fill="#fbf7ee", block_background_fill_dark="#221f19",
        block_border_color="#d6ccbb", block_border_color_dark="#514838",
        border_color_primary="#d6ccbb", border_color_primary_dark="#514838",
        block_label_text_color="#5a4f42", block_label_text_color_dark="#b3a88f",
        block_title_text_color="#1f1a14", block_title_text_color_dark="#ece3d2",
        input_background_fill="#fffdf8", input_background_fill_dark="#28241d",
        input_background_fill_focus="#fffdf8", input_background_fill_focus_dark="#28241d",
        input_border_color="#d6ccbb", input_border_color_dark="#514838",
        input_border_color_focus="#8a2b2b", input_border_color_focus_dark="#d98a8a",
        input_placeholder_color="#796c5c", input_placeholder_color_dark="#b3a88f",
        button_primary_background_fill="#8a2b2b", button_primary_background_fill_dark="#a84343",
        button_primary_background_fill_hover="#6f2020", button_primary_background_fill_hover_dark="#8a2b2b",
        button_primary_border_color="#8a2b2b", button_primary_border_color_dark="#a84343",
        button_primary_text_color="#fffdf8", button_primary_text_color_dark="#fffdf8",
        button_secondary_background_fill="#fbf7ee", button_secondary_background_fill_dark="#221f19",
        button_secondary_background_fill_hover="#efe8da", button_secondary_background_fill_hover_dark="#28241d",
        button_secondary_border_color="#d6ccbb", button_secondary_border_color_dark="#514838",
        button_secondary_text_color="#5a4f42", button_secondary_text_color_dark="#ece3d2",
        link_text_color="#8a2b2b", link_text_color_dark="#d98a8a",
        accordion_text_color="#5a4f42", accordion_text_color_dark="#b3a88f",
        block_radius="4px", container_radius="4px", input_radius="4px",
        block_shadow="none", block_shadow_dark="none",
        button_primary_shadow="none", button_secondary_shadow="none",
        loader_color="#8a2b2b", loader_color_dark="#d98a8a",
    )
    return {"css": asset_text("editorial.css"), "theme": theme, "footer_links": []}
