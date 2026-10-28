import { createRef, useRef, useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { Composer } from "@/components/composer";

it("does not submit an IME confirmation, its legacy key event, or Shift+Enter", () => {
  const submit = vi.fn();
  render(<Composer value="A draft" onChange={vi.fn()} onSubmit={submit} onStop={vi.fn()} busy={false} inputRef={createRef<HTMLTextAreaElement>()} />);
  const input = screen.getByRole("textbox");
  fireEvent.keyDown(input, { key: "Enter", isComposing: true });
  fireEvent.keyDown(input, { key: "Enter", keyCode: 229 });
  fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
  expect(submit).not.toHaveBeenCalled();
  fireEvent.keyDown(input, { key: "Enter" });
  expect(submit).toHaveBeenCalledOnce();
});

it("keeps the dock focused while focus moves from the question to Send", async () => {
  const focus = vi.fn();
  const submit = vi.fn();
  const user = userEvent.setup();
  render(<>
    <Composer
      value="Help me prepare to renew my licence."
      onChange={vi.fn()}
      onSubmit={submit}
      onStop={vi.fn()}
      busy={false}
      inputRef={createRef<HTMLTextAreaElement>()}
      onFocusChange={focus}
    />
    <button>Outside the composer</button>
  </>);
  await user.click(screen.getByRole("textbox"));
  await user.tab();
  const send = screen.getByRole("button", { name: "Send question" });
  expect(send).toHaveFocus();
  expect(focus.mock.calls.every(([value]) => value === true)).toBe(true);
  await user.click(send);
  expect(submit).toHaveBeenCalledTimes(1);
  await user.tab();
  expect(screen.getByRole("button", { name: "Outside the composer" })).toHaveFocus();
  expect(focus).toHaveBeenLastCalledWith(false);
});

it.each(["click", "Enter", "Space"])("stopping with %s does not resubmit the restored prompt", async (action) => {
  const prompt = "Help me prepare to renew my licence.";
  const stop = vi.fn();
  const submit = vi.fn();
  const user = userEvent.setup();
  function RunningComposer() {
    const [busy, setBusy] = useState(true);
    const [value, setValue] = useState("");
    const inputRef = useRef<HTMLTextAreaElement>(null);
    return <Composer
      value={value}
      onChange={setValue}
      onSubmit={submit}
      onStop={() => {
        stop();
        setValue(prompt);
        setBusy(false);
      }}
      busy={busy}
      inputRef={inputRef}
    />;
  }
  render(<RunningComposer />);
  const button = screen.getByRole("button", { name: "Stop answer" });
  if (action === "click") await user.click(button);
  else {
    button.focus();
    await user.keyboard(action === "Enter" ? "{Enter}" : "[Space]");
  }
  expect(stop).toHaveBeenCalledTimes(1);
  expect(submit).not.toHaveBeenCalled();
  expect(screen.getByRole("textbox")).toHaveValue(prompt);
  await user.click(screen.getByRole("button", { name: "Send question" }));
  expect(submit).toHaveBeenCalledTimes(1);
});
