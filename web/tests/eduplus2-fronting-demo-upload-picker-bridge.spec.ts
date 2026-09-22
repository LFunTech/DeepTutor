import { screen } from "@testing-library/dom";
import { describe, expect, it, vi } from "vitest";

import { installEduPlus2ResourceUploadPickerBridge } from "@/lib/eduplus2-fronting-demo-upload-picker-bridge";

describe("EduPlus2 fronting demo upload picker cache bridge", () => {
  it("reveals a stale cached resource file input as a native clickable control", () => {
    document.body.innerHTML = `
      <section>
        <h2>真实 /api/v1/ws 对话测试</h2>
        <label class="mt-3 block text-xs font-black">
          选择图片、音频、视频或文档文件
          <input
            type="file"
            multiple
            class="sr-only"
          />
        </label>
      </section>
    `;
    const input = screen.getByLabelText(
      "选择图片、音频、视频或文档文件",
    ) as HTMLInputElement;

    const uninstall = installEduPlus2ResourceUploadPickerBridge(document);

    expect(screen.queryByRole("button", { name: "选择文件" })).not.toBeInTheDocument();
    expect(input).not.toHaveClass("sr-only");
    expect(input).toHaveClass("cursor-pointer");
    expect(input).toHaveAttribute("aria-labelledby", "eduplus2-resource-upload-label");
    uninstall();
  });

  it("keeps the fresh native file input path free of JavaScript proxy buttons", () => {
    document.body.innerHTML = `
      <section>
        <p id="eduplus2-resource-upload-label">选择图片、音频、视频或文档文件</p>
        <div>
          <input
            type="file"
            multiple
            aria-labelledby="eduplus2-resource-upload-label"
            class="block w-full cursor-pointer rounded-2xl"
          />
        </div>
      </section>
    `;
    const input = screen.getByLabelText(
      "选择图片、音频、视频或文档文件",
    ) as HTMLInputElement;

    const uninstall = installEduPlus2ResourceUploadPickerBridge(document);

    expect(screen.queryByRole("button", { name: "选择文件" })).not.toBeInTheDocument();
    expect(input).not.toHaveClass("sr-only");
    uninstall();
  });
});
