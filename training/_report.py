"""Consistent console output for the training / data-export scripts.

Before this, each script printed in its own ad-hoc style (mixed "Done." blocks,
differently-aligned summaries). These helpers give the whole training pipeline one
look, matching the rich-based benchmark scripts in tests/.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

_console = Console()


def banner(title: str, subtitle: str = "") -> None:
    """Top-of-run header."""
    body = f"[bold cyan]{title}[/bold cyan]"
    if subtitle:
        body += f"\n[dim]{subtitle}[/dim]"
    _console.print(Panel(body, expand=False, border_style="cyan"))


def step(msg: str) -> None:
    """A single progress line."""
    _console.print(f"[cyan]›[/cyan] {msg}")


def warn(msg: str) -> None:
    _console.print(f"[yellow]![/yellow] {msg}")


def summary(title: str, **fields) -> None:
    """End-of-run key/value summary block."""
    table = Table(title=title, title_style="bold green", show_header=False, border_style="green")
    table.add_column("field", style="bold")
    table.add_column("value")
    for key, value in fields.items():
        table.add_row(key.replace("_", " "), str(value))
    _console.print(table)
