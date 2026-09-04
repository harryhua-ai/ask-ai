/** #16 RepoDiscoveryPanel + PolicyChips 呈现层测试。

冻结纪律:推荐/理由/能力边界均为后端产物,面板只分组直呈;
「采用推荐策略」必须原样上送 recommended_config,不做本地二次推导。
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import {
  applyRepoDecisions,
  RepoDiscoveryPanel,
  PolicyChips,
} from "@/components/dataSources/RepoDiscoveryPanel";
import type { RepoDiscoveryResult } from "@/types/api";

afterEach(cleanup);

const fixture: RepoDiscoveryResult = {
  kind: "github",
  target: { owner: "camthink-ai", repo: "demo", branch: "main" },
  totals: { files: 5, safe_files: 4, unsafe_files: 1, total_size: 1650 },
  by_role: {},
  groups: [
    { key: "(根目录)", count: 1, total_size: 200, recommendation: "include", samples: ["README.md"] },
    { key: "src", count: 1, total_size: 1000, recommendation: "include", samples: ["src/main.py"] },
    { key: "tests", count: 1, total_size: 300, recommendation: "exclude", samples: ["tests/test_main.py"] },
    { key: "assets", count: 1, total_size: 100, recommendation: "review", samples: ["assets/logo.png"] },
    { key: "deploy", count: 1, total_size: 50, recommendation: "exclude", samples: ["deploy/id_rsa"] },
  ],
  candidates: [
    { path: "README.md", size: 200, technical_safe: true, technical_reason: null, knowledge_role: "technical_doc", recommendation: "include", policy_result: "not_applied", eligible: true, reason: "属于技术文档,建议纳入" },
    { path: "src/main.py", size: 1000, technical_safe: true, technical_reason: null, knowledge_role: "source_code", recommendation: "include", policy_result: "not_applied", eligible: true, reason: "属于源代码,建议纳入" },
    { path: "tests/test_main.py", size: 300, technical_safe: true, technical_reason: null, knowledge_role: "test", recommendation: "exclude", policy_result: "not_applied", eligible: true, reason: "知识价值低(测试代码),建议排除" },
    { path: "assets/logo.png", size: 100, technical_safe: true, technical_reason: null, knowledge_role: "binary", recommendation: "review", policy_result: "not_applied", eligible: true, reason: "需要人工确认(二进制资产)" },
    { path: "deploy/id_rsa", size: 50, technical_safe: false, technical_reason: "secret_file", knowledge_role: "secrets", recommendation: "exclude", policy_result: "not_applied", eligible: false, reason: "疑似密钥/凭证文件,技术安全边界禁止纳入" },
  ],
  recommended_config: { file_types: [".md", ".py"], exclude_dirs: ["deploy", "tests"] },
  warnings: ["仓库文件树过大,远端结果已截断,统计可能不完整(建议缩小范围或使用高级模式)"],
  capability_notes: [
    "图片/音视频资产:当前 ingestion 管线为文本抽取,不支持图片理解——此类文件已标记「待确认」且默认不纳入,不会因仓库中存在而默认声明支持",
  ],
};

describe("RepoDiscoveryPanel", () => {
  it("三段推荐分组直呈:include/exclude/review 各归其位", () => {
    render(<RepoDiscoveryPanel result={fixture} onApply={vi.fn()} />);
    expect(screen.getByText("建议纳入")).toBeInTheDocument();
    expect(screen.getByText("建议排除")).toBeInTheDocument();
    expect(screen.getByText("待人工确认")).toBeInTheDocument();
    // 分组键可见:src(include)/ tests(exclude,分组与推荐 chips 各一处)/ assets(review)
    expect(screen.getByText("src")).toBeInTheDocument();
    expect(screen.getAllByText("tests").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("assets")).toBeInTheDocument();
  });

  it("冻结理由原文呈现,前端不重判(密钥/测试/图片各按后端文案)", () => {
    render(<RepoDiscoveryPanel result={fixture} onApply={vi.fn()} />);
    expect(
      screen.getByText("疑似密钥/凭证文件,技术安全边界禁止纳入"),
    ).toBeInTheDocument();
    expect(screen.getByText("知识价值低(测试代码),建议排除")).toBeInTheDocument();
    expect(screen.getByText("需要人工确认(二进制资产)")).toBeInTheDocument();
  });

  it("技术安全限制计数与告警原文可见", () => {
    render(<RepoDiscoveryPanel result={fixture} onApply={vi.fn()} />);
    expect(screen.getByText(/1 个存在技术安全限制/)).toBeInTheDocument();
    expect(
      screen.getByText(/仓库文件树过大,远端结果已截断/),
    ).toBeInTheDocument();
  });

  it("能力边界诚实:图片默认不纳入的声明可见(可展开)", () => {
    render(<RepoDiscoveryPanel result={fixture} onApply={vi.fn()} />);
    const details = screen.getByText("能力边界说明");
    fireEvent.click(details);
    expect(screen.getByText(/不支持图片理解/)).toBeInTheDocument();
  });

  it("采用推荐策略 = recommended_config 原样上送(零本地改写)", () => {
    const onApply = vi.fn();
    render(<RepoDiscoveryPanel result={fixture} onApply={onApply} />);
    fireEvent.click(screen.getByText("采用推荐策略"));
    expect(onApply).toHaveBeenCalledWith({
      file_types: [".md", ".py"],
      exclude_dirs: ["deploy", "tests"],
    });
  });

  it("review 组给默认不纳入提示;空 exclude 组显示无", () => {
    const thin: RepoDiscoveryResult = {
      ...fixture,
      warnings: [],
      groups: fixture.groups.filter((g) => g.recommendation !== "exclude"),
      candidates: fixture.candidates.filter((c) => c.recommendation !== "exclude"),
      recommended_config: { file_types: [".md", ".py"], exclude_dirs: [] },
    };
    render(<RepoDiscoveryPanel result={thin} onApply={vi.fn()} />);
    // #22 有意更新:review 组提示改为「可就地决策 + 策略记忆」语义(旧文案
    // 「待确认项默认不纳入」是 #22 之前的常态评审语义,已被冻结契约替换)
    expect(screen.getByText(/仅真正无法安全判定的组需要决定/)).toBeInTheDocument();
    expect(screen.getAllByText("无").length).toBeGreaterThanOrEqual(1);
  });
});

describe("PolicyChips", () => {
  it("两组均空时不渲染", () => {
    const { container } = render(
      <PolicyChips fileTypes={[]} excludeDirs={[]} onChange={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("移除单个文件类型并把变更回传(与表单字段同源)", () => {
    const onChange = vi.fn();
    render(
      <PolicyChips
        fileTypes={[".md", ".py"]}
        excludeDirs={["tests"]}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByLabelText("移除 .md"));
    expect(onChange).toHaveBeenCalledWith({ file_types: [".py"], exclude_dirs: ["tests"] });
    fireEvent.click(screen.getByLabelText("移除 tests"));
    expect(onChange).toHaveBeenCalledWith({ file_types: [".md", ".py"], exclude_dirs: [] });
  });

  it("添加去重:输入已有类型不再追加", () => {
    const onChange = vi.fn();
    render(
      <PolicyChips fileTypes={[".md"]} excludeDirs={[]} onChange={onChange} />,
    );
    const input = screen.getByLabelText("添加文件类型");
    fireEvent.change(input, { target: { value: ".md" } });
    fireEvent.blur(input);
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: ".CSV" } });
    fireEvent.blur(input);
    expect(onChange).toHaveBeenCalledWith({ file_types: [".md", ".csv"], exclude_dirs: [] });
  });
});

describe("#22 组决策合成(applyRepoDecisions)", () => {
  it("include 决策并入该组安全成员扩展名并移出排除;exclude 决策目录进排除", () => {
    // assets 组(binary → producer L1 排除后若决策纳入)与 misc 组决策演示:
    const decisions = { assets: "include" as const };
    const out = applyRepoDecisions(fixture, decisions);
    // assets/logo.png 技术安全 → .png 进白名单;assets 移出排除(本就不在)
    expect(out.file_types).toContain(".png");
    expect(out.file_types).toEqual([".md", ".png", ".py"]);
    // deploy 仍排除;决策未触碰 deploy
    expect(out.exclude_dirs).toEqual(["deploy", "tests"]);
  });

  it("exclude 决策把目录写入排除(connector 语义:排除目录胜过白名单)", () => {
    const out = applyRepoDecisions(fixture, { src: "exclude" as const });
    expect(out.exclude_dirs).toContain("src");
    expect(out.file_types).toContain(".py"); // 白名单仍含 .py,但 src 目录整体被排除
  });

  it("恢复推荐(删除决策)按基线重算,幂等可逆", () => {
    const withDecision = applyRepoDecisions(fixture, { assets: "include" as const });
    const reverted = applyRepoDecisions(fixture, {});
    expect(reverted.file_types).toEqual(fixture.recommended_config.file_types);
    expect(reverted.exclude_dirs).toEqual(fixture.recommended_config.exclude_dirs);
    expect(withDecision.file_types).not.toEqual(reverted.file_types);
  });

  it("include 决策不并入技术不安全成员的扩展名(L1 不可覆盖)", () => {
    const result = {
      ...fixture,
      candidates: fixture.candidates.map((c) =>
        c.path === "assets/logo.png" ? { ...c, technical_safe: false } : c,
      ),
    };
    const out = applyRepoDecisions(result, { assets: "include" as const });
    expect(out.file_types).toEqual([".md", ".py"]);
  });
});

describe("#22 组决策控件(UI)", () => {
  it("待人工确认组提供纳入/排除控件;点击回传组决策;已决定后可恢复推荐", () => {
    const onDecide = vi.fn();
    render(
      <RepoDiscoveryPanel
        result={fixture}
        decisions={{}}
        onDecide={onDecide}
        onApply={vi.fn()}
      />,
    );
    // review 组(assets)行内出现决策控件;纳入可点击
    const includeButtons = screen.getAllByText("纳入");
    expect(includeButtons.length).toBeGreaterThanOrEqual(1);
    // 点击第一个「纳入」回传对应组(排序首组 = "(根目录)")
    fireEvent.click(includeButtons[0]);
    expect(onDecide).toHaveBeenCalledWith("(根目录)", "include");
    // 排除控件存在
    expect(screen.getAllByText("排除").length).toBeGreaterThanOrEqual(1);
  });

  it("已决定组显示已决定 + 恢复推荐;规则继承组显示「已按策略」徽章", () => {
    const decided: RepoDiscoveryResult = {
      ...fixture,
      groups: fixture.groups.map((g) =>
        g.key === "assets" ? { ...g, admin_decision: "include" as const } : g,
      ),
    };
    render(
      <RepoDiscoveryPanel
        result={decided}
        decisions={{ assets: "include" }}
        onDecide={vi.fn()}
        onApply={vi.fn()}
      />,
    );
    expect(screen.getAllByText("已按策略").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/恢复推荐/).length).toBeGreaterThanOrEqual(1);
  });

  it("scope_confirmed=false 的 include 组显示范围未确认告警", () => {
    const unconfirmed: RepoDiscoveryResult = {
      ...fixture,
      groups: fixture.groups.map((g) =>
        g.key === "src" ? { ...g, scope_confirmed: false } : g,
      ),
    };
    render(<RepoDiscoveryPanel result={unconfirmed} onApply={vi.fn()} />);
    expect(screen.getByTitle(/该组有建议纳入文件不在生效策略范围内/)).toBeInTheDocument();
  });
});
