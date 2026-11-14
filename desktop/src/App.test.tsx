import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./engine/api", async (original) => ({
  ...(await original<typeof import("./engine/api")>()),
  getSettings: vi.fn(),
  library: vi.fn(),
  locateEngine: vi.fn(),
  run: vi.fn(),
  describe: vi.fn(),
}));

import * as api from "./engine/api";
import App from "./App";

beforeEach(() => {
  vi.mocked(api.getSettings).mockResolvedValue({
    cli_path: null,
    uv_project: null,
    output_dir: null,
    theme: "light",
    added_books: [],
  });
  vi.mocked(api.library).mockResolvedValue({ output_dir: "/out", min_boundary_confidence: 0.75, books: [], commands: [] });
  vi.mocked(api.locateEngine).mockReturnValue(new Promise(() => {}));
});

describe("App shell", () => {
  it("opens on the library with the rail's three destinations", async () => {
    render(<App />);
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Library" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "Run" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("heading", { level: 1, name: "Library" })).toBeInTheDocument();
    expect(await screen.findByText("No books yet")).toBeInTheDocument();
  });

  it("applies the saved theme", async () => {
    render(<App />);
    await screen.findByText("No books yet");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("moves between destinations with the keyboard", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.tab();
    expect(screen.getByRole("button", { name: "Library" })).toHaveFocus();
    await user.tab();
    await user.tab();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: "Settings" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("main", { name: "Setup" })).toBeInTheDocument();
  });
});
