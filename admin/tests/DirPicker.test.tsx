import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { DirPicker } from "@/components/DirPicker";
import { ApiError } from "@/lib/api";
import { usePreviewDirs } from "@/hooks/useDataSources";

vi.mock("@/hooks/useDataSources", () => ({
  usePreviewDirs: vi.fn(),
}));

const mockedPreview = vi.mocked(usePreviewDirs);

describe("DirPicker 缺目录友好态", () => {
  beforeEach(() => {
    mockedPreview.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it("传入 missingHint 且 404 时展示友好提示而非报错", () => {
    mockedPreview.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new ApiError(404, "目录不存在: data/uploads/data-sources/x"),
    } as never);
    render(
      <DirPicker
        rootPath="data/uploads/data-sources/x"
        value={[]}
        onChange={() => {}}
        missingHint="该源还没有上传过文件"
      />,
    );
    expect(screen.getByText("该源还没有上传过文件")).toBeInTheDocument();
    expect(screen.queryByText(/目录加载失败/)).not.toBeInTheDocument();
  });

  it("未传 missingHint 时 404 仍按错误显示(服务器路径模式需要真实报错)", () => {
    mockedPreview.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new ApiError(404, "目录不存在: /data/docs"),
    } as never);
    render(<DirPicker rootPath="/data/docs" value={[]} onChange={() => {}} />);
    expect(screen.getByText(/目录加载失败/)).toBeInTheDocument();
  });

  it("非 404 错误即使有 missingHint 也按错误显示", () => {
    mockedPreview.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new ApiError(500, "服务器内部错误"),
    } as never);
    render(
      <DirPicker
        rootPath="data/uploads/data-sources/x"
        value={[]}
        onChange={() => {}}
        missingHint="该源还没有上传过文件"
      />,
    );
    expect(screen.getByText(/目录加载失败/)).toBeInTheDocument();
  });
});
