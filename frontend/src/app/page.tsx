import { HealthPanel } from "@/components/health-panel";

const principles = [
  ["只读数据", "四份 Tara 源数据保持不变，派生文件与源文件隔离。"],
  ["确定性分析", "科学计算由可测试的后端函数完成，不交给模型自由执行。"],
  ["清晰边界", "前端负责交互和展示，后端负责 Agent、工具和分析。"],
];

export default function Home() {
  return (
    <main>
      <section className="hero">
        <p className="eyebrow">Tara Oceans · MVP</p>
        <h1>用自然语言探索海洋数据</h1>
        <p className="lead">
          工程基础已经就绪。下一增量将从样本与环境信息查询开始，逐步接入可追踪的分析工具。
        </p>
      </section>

      <HealthPanel />

      <section className="principles" aria-labelledby="principles-title">
        <div>
          <p className="eyebrow">Architecture</p>
          <h2 id="principles-title">设计边界</h2>
        </div>
        <div className="principle-grid">
          {principles.map(([title, detail]) => (
            <article key={title}>
              <h3>{title}</h3>
              <p>{detail}</p>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}

