import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Button } from "./Button";
import { Card } from "./Card";
import { Checkbox } from "./Checkbox";
import { AssistChip, ChipSet, FilterChip } from "./Chip";
import { Dialog } from "./Dialog";
import { Icon } from "./Icon";
import { IconButton } from "./IconButton";
import { NavigationRail } from "./NavigationRail";
import { PlayerBar } from "./PlayerBar";
import { CircularProgress, LinearProgress } from "./Progress";
import { Select } from "./Select";
import { Slider } from "./Slider";
import { Snackbar } from "./Snackbar";
import { Switch } from "./Switch";
import { TextField } from "./TextField";
import { TopAppBar } from "./TopAppBar";
import { ICONS } from "../theme/icons.generated";

function element(container: HTMLElement, tag: string): HTMLElement & Record<string, unknown> {
  const found = container.querySelector(tag);
  if (!found) throw new Error(`${tag} not rendered`);
  return found as HTMLElement & Record<string, unknown>;
}

function fire(target: HTMLElement, name: string) {
  act(() => {
    target.dispatchEvent(new Event(name, { bubbles: true }));
  });
}

describe("Icon", () => {
  it("draws the codepoint from the subset font and hides it from screen readers", () => {
    const { container } = render(<Icon name="settings" filled size={20} />);
    const icon = container.querySelector("span") as HTMLElement;
    expect(icon.textContent).toBe(String.fromCodePoint(ICONS.settings));
    expect(icon).toHaveAttribute("aria-hidden", "true");
    expect(icon.style.fontVariationSettings).toContain('"FILL" 1');
    expect(icon.style.fontSize).toBe("20px");
  });
});

describe("@material/web wrappers", () => {
  it.each([
    ["filled", "md-filled-button"],
    ["tonal", "md-filled-tonal-button"],
    ["outlined", "md-outlined-button"],
    ["text", "md-text-button"],
  ] as const)("Button %s renders %s and reports clicks", (variant, tag) => {
    const onClick = vi.fn();
    const { container } = render(
      <Button variant={variant} icon="add" onClick={onClick}>
        Add book
      </Button>,
    );
    const button = element(container, tag);
    expect(button).toHaveTextContent("Add book");
    expect(customElements.get(tag)).toBeDefined();
    fire(button, "click");
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("a disabled Button does not report clicks", () => {
    const onClick = vi.fn();
    const { container } = render(
      <Button disabled onClick={onClick}>
        Convert
      </Button>,
    );
    fire(element(container, "md-filled-button"), "click");
    expect(onClick).not.toHaveBeenCalled();
  });

  it("IconButton has an accessible name", () => {
    const onClick = vi.fn();
    const { container } = render(<IconButton icon="close" label="Close" onClick={onClick} />);
    const button = element(container, "md-icon-button");
    expect(button).toHaveAttribute("aria-label", "Close");
    fire(button, "click");
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("TextField reports typed values and shows an error", () => {
    const onChange = vi.fn();
    const { container } = render(
      <TextField label="Model" value="" onChange={onChange} errorText="Required" />,
    );
    const field = element(container, "md-outlined-text-field");
    expect(field.label).toBe("Model");
    expect(field.error).toBe(true);
    expect(field.errorText).toBe("Required");
    field.value = "qwen";
    fire(field, "input");
    expect(onChange).toHaveBeenCalledWith("qwen");
  });

  it("Switch, Checkbox and FilterChip report their new state", () => {
    const onSwitch = vi.fn();
    const onCheck = vi.fn();
    const onChip = vi.fn();
    const { container } = render(
      <>
        <Switch label="Use the LLM" selected={false} onChange={onSwitch} />
        <Checkbox label="I reviewed it" checked={false} onChange={onCheck} />
        <ChipSet>
          <FilterChip label="Pending" selected onChange={onChip} />
        </ChipSet>
      </>,
    );
    const toggle = element(container, "md-switch");
    toggle.selected = true;
    fire(toggle, "change");
    expect(onSwitch).toHaveBeenCalledWith(true);
    const box = element(container, "md-checkbox");
    box.checked = true;
    fire(box, "change");
    expect(onCheck).toHaveBeenCalledWith(true);
    fire(element(container, "md-filter-chip"), "click");
    expect(onChip).toHaveBeenCalledWith(false);
    expect(screen.getByText("Use the LLM")).toBeInTheDocument();
  });

  it("Select and Slider report their values", () => {
    const onSelect = vi.fn();
    const onSlide = vi.fn();
    const { container } = render(
      <>
        <Select
          label="Voice"
          value="Jasper"
          options={[
            { value: "Jasper", label: "Jasper" },
            { value: "Luna", label: "Luna" },
          ]}
          onChange={onSelect}
        />
        <Slider label="Speed" value={1} min={0.5} max={2} step={0.05} onChange={onSlide} />
      </>,
    );
    const select = element(container, "md-outlined-select");
    expect(container.querySelectorAll("md-select-option")).toHaveLength(2);
    // jsdom doesn't compute a select's value from its slotted options; pin the getter.
    vi.spyOn(Object.getPrototypeOf(select), "value", "get").mockReturnValue("Luna");
    fire(select, "change");
    expect(onSelect).toHaveBeenCalledWith("Luna");
    const slider = element(container, "md-slider");
    expect(slider).toHaveAttribute("aria-label", "Speed");
    slider.value = 1.25;
    fire(slider, "change");
    expect(onSlide).toHaveBeenCalledWith(1.25);
  });

  it("Dialog reports every close", () => {
    const onClose = vi.fn();
    const { container } = render(
      <Dialog open headline="Accept all?" actions={<span>actions</span>} onClose={onClose}>
        Accept 12 edits.
      </Dialog>,
    );
    const dialog = element(container, "md-dialog");
    expect(dialog).toHaveTextContent("Accept all?");
    fire(dialog, "closed");
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("progress indicators are labelled and expose their value", () => {
    render(
      <>
        <LinearProgress value={0.25} label="Synthesis" />
        <CircularProgress label="Loading" />
      </>,
    );
    expect(screen.getByRole("progressbar", { name: "Synthesis" })).toHaveAttribute(
      "aria-valuenow",
      "25",
    );
    const loading = screen.getByRole("progressbar", { name: "Loading" }) as HTMLElement & {
      indeterminate: boolean;
    };
    expect(loading.indeterminate).toBe(true);
  });

  it("AssistChip reports clicks", () => {
    const onClick = vi.fn();
    const { container } = render(<AssistChip label="Open folder" icon="folder_open" onClick={onClick} />);
    fire(element(container, "md-assist-chip"), "click");
    expect(onClick).toHaveBeenCalledOnce();
  });
});

describe("shell components", () => {
  const destinations = [
    { id: "library", label: "Library", icon: "library_books" },
    { id: "settings", label: "Settings", icon: "settings" },
  ] as const;

  it("NavigationRail marks the current destination and selects with the keyboard", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<NavigationRail destinations={destinations} current="library" onSelect={onSelect} />);
    expect(screen.getByRole("button", { name: "Library" })).toHaveAttribute("aria-current", "page");
    await user.tab();
    await user.tab();
    await user.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledWith("settings");
  });

  it("TopAppBar is the page heading", () => {
    render(<TopAppBar title="Library" actions={<button type="button">Add</button>} />);
    expect(screen.getByRole("heading", { level: 1, name: "Library" })).toBeInTheDocument();
  });

  it("an interactive Card is a named button", async () => {
    const onOpen = vi.fn();
    render(
      <Card label="Open The Lighthouse" onOpen={onOpen}>
        The Lighthouse
      </Card>,
    );
    await userEvent.setup().click(screen.getByRole("button", { name: "Open The Lighthouse" }));
    expect(onOpen).toHaveBeenCalledOnce();
  });

  it("Snackbar announces its message politely", () => {
    const { rerender } = render(<Snackbar message={null} />);
    const region = screen.getByRole("status");
    expect(region).toHaveAttribute("aria-live", "polite");
    expect(region).toBeEmptyDOMElement();
    rerender(<Snackbar message="Saved" />);
    expect(region).toHaveTextContent("Saved");
  });

  it("PlayerBar shows the chapter and toggles play", () => {
    const onToggle = vi.fn();
    const { container, rerender } = render(
      <PlayerBar title="Chapter 3" subtitle="The Lighthouse" playing={false} position={0.5} onTogglePlay={onToggle} onClose={() => {}} />,
    );
    expect(screen.getByRole("region", { name: "Player" })).toHaveTextContent("Chapter 3");
    const play = container.querySelector('[aria-label="Play"]') as HTMLElement;
    fire(play, "click");
    expect(onToggle).toHaveBeenCalledOnce();
    rerender(
      <PlayerBar title="Chapter 3" subtitle="The Lighthouse" playing position={0.5} onTogglePlay={onToggle} onClose={() => {}} />,
    );
    expect(container.querySelector('[aria-label="Pause"]')).not.toBeNull();
    expect(container.querySelector('[aria-label="Previous chapter"]')).toHaveAttribute("disabled");
  });
});
