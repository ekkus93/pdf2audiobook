import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "./App";

describe("App", () => {
  it("renders the empty application shell", () => {
    render(<App />);
    expect(screen.getByRole("main", { name: "pdf2audiobook" })).toBeInTheDocument();
  });
});
