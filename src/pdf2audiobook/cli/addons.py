"""The desktop app's optional add-ons (self-contained app spec SC3)."""

import typer

from pdf2audiobook.cli._core import ClickExit, addons_app, console, emit, fail, fail_interrupted
from pdf2audiobook.errors import ConfigError
from pdf2audiobook.logging import set_output_mode


@addons_app.command("list", epilog="Example: pdf2audiobook addons list --json")
def addons_list(json_output: bool = typer.Option(False, "--json")) -> None:
    """Show each add-on and whether it is installed for this engine version."""
    set_output_mode(json_output)
    try:
        from pdf2audiobook import addons

        report = addons.status()
        if json_output:
            emit({"available": addons.lists() is not None, "addons": report}, json_output)
            return
        if not report:
            console.print("Add-ons are available only in the desktop app's built-in engine.")
        for item in report:
            console.print(
                f"{item['name']}: {item['title']} ({'installed' if item['installed'] else 'not installed'})"
            )
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)


@addons_app.command("install", epilog="Example: pdf2audiobook addons install kitten2 --yes --json")
def addons_install(
    name: str = typer.Argument(..., help="kitten2 or audio-check."),
    yes: bool = typer.Option(False, "--yes", help="Download and install without asking first."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Download and install an add-on's packages and models, checking every file's hash."""
    set_output_mode(json_output)
    try:
        from pdf2audiobook import addons

        if not yes:
            if json_output:
                raise ConfigError("Review 'addons list --json', then pass --yes to install")
            if not typer.confirm(
                f"Download and install the {name} add-on?", default=False, err=True
            ):
                raise typer.Exit(1)
        emit({"addon": addons.install(name)}, json_output)
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)


@addons_app.command("remove", epilog="Example: pdf2audiobook addons remove kitten2 --json")
def addons_remove(
    name: str = typer.Argument(..., help="kitten2 or audio-check."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Remove an add-on, keeping packages another installed add-on still needs."""
    set_output_mode(json_output)
    try:
        from pdf2audiobook import addons

        emit({"addon": addons.remove(name)}, json_output)
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)


@addons_app.command("languages", epilog="Example: pdf2audiobook addons languages --json")
def addons_languages(json_output: bool = typer.Option(False, "--json")) -> None:
    """List OCR languages that are ready and those that can be added."""
    set_output_mode(json_output)
    try:
        from pdf2audiobook import addons

        report = addons.languages()
        if json_output:
            emit(report, json_output)
        else:
            console.print("Ready: " + (", ".join(report["installed"]) or "none"))
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)


@addons_app.command(
    "add-language", epilog="Example: pdf2audiobook addons add-language deu --yes --json"
)
def addons_add_language(
    codes: list[str] = typer.Argument(..., help="Tesseract language codes, such as deu or fra."),
    yes: bool = typer.Option(False, "--yes", help="Download without asking first."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Download OCR languages, checking each file against its pinned size and hash."""
    set_output_mode(json_output)
    try:
        from pdf2audiobook import addons

        if not yes:
            if json_output:
                raise ConfigError("Review 'addons languages --json', then pass --yes to download")
            if not typer.confirm(
                f"Download OCR data for {', '.join(codes)}?", default=False, err=True
            ):
                raise typer.Exit(1)
        emit(addons.add_languages(codes), json_output)
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)


@addons_app.command(
    "remove-language", epilog="Example: pdf2audiobook addons remove-language deu --json"
)
def addons_remove_language(
    code: str = typer.Argument(..., help="An added OCR language code."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Remove an added OCR language; the built-in ones stay."""
    set_output_mode(json_output)
    try:
        from pdf2audiobook import addons

        emit(addons.remove_language(code), json_output)
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)
