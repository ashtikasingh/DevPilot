import RepositoryImportPanel from "@/components/repository-import-panel";

type IconName =
  | "overview"
  | "repository"
  | "memory"
  | "guardian"
  | "settings"
  | "arrow"
  | "github"
  | "code"
  | "question"
  | "pulse"
  | "clock"
  | "branch"
  | "check"
  | "spark";

function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  const shared = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.7,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true as const,
  };

  switch (name) {
    case "overview":
      return <svg {...shared}><rect x="3.5" y="3.5" width="7" height="7" rx="1.5" /><rect x="13.5" y="3.5" width="7" height="7" rx="1.5" /><rect x="3.5" y="13.5" width="7" height="7" rx="1.5" /><rect x="13.5" y="13.5" width="7" height="7" rx="1.5" /></svg>;
    case "repository":
      return <svg {...shared}><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5z" /><path d="M4 5.5v15M8 7h8M8 11h6" /></svg>;
    case "memory":
      return <svg {...shared}><path d="M12 3v18M5.6 6.2l12.8 11.6M18.4 6.2 5.6 17.8" /><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="2.2" /></svg>;
    case "guardian":
      return <svg {...shared}><path d="M12 3 20 6v5.5c0 4.5-3.1 7.7-8 9.5-4.9-1.8-8-5-8-9.5V6z" /><path d="m9 12 2 2 4-4" /></svg>;
    case "settings":
      return <svg {...shared}><circle cx="12" cy="12" r="3" /><path d="m19.4 15 .1.1 1.2 2.1-2.1 2.1-2.2-1.2-.2.1a8 8 0 0 1-1.5.6l-.2.1-.5 2.4h-3l-.5-2.4-.2-.1a8 8 0 0 1-1.5-.6l-.2-.1-2.2 1.2-2.1-2.1 1.2-2.1.1-.2a8 8 0 0 1-.6-1.5l-.1-.2L2.8 12v-3l2.4-.5.1-.2a8 8 0 0 1 .6-1.5l.1-.2-1.2-2.2 2.1-2.1 2.1 1.2.2.1a8 8 0 0 1 1.5-.6l.2-.1.5-2.4h3l.5 2.4.2.1a8 8 0 0 1 1.5.6l.2-.1 2.2-1.2 2.1 2.1-1.2 2.1-.1.2a8 8 0 0 1 .6 1.5l.1.2 2.4.5v3l-2.4.5-.1.2a8 8 0 0 1-.6 1.5z" transform="translate(1 1) scale(.92)" /></svg>;
    case "arrow":
      return <svg {...shared}><path d="M5 12h14M13 6l6 6-6 6" /></svg>;
    case "github":
      return <svg {...shared}><path d="M9 19c-4.3 1.4-4.3-2.5-6-3m12 6v-3.9a3.4 3.4 0 0 0-.9-2.6c3-.3 6.1-1.5 6.1-6.8a5.3 5.3 0 0 0-1.4-3.7 4.9 4.9 0 0 0-.1-3.7s-1.2-.4-3.9 1.4a13.5 13.5 0 0 0-7.1 0C5 1 3.8 1.4 3.8 1.4a4.9 4.9 0 0 0-.1 3.7 5.3 5.3 0 0 0-1.4 3.7c0 5.3 3.1 6.5 6.1 6.8a3.4 3.4 0 0 0-.9 2.6V22" transform="translate(2 1) scale(.84)" /></svg>;
    case "code":
      return <svg {...shared}><path d="m8 8-4 4 4 4m8-8 4 4-4 4m-3-11-2 14" /></svg>;
    case "question":
      return <svg {...shared}><path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8A8.5 8.5 0 0 1 8.7 4a8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8z" /><path d="M9.8 9a2.3 2.3 0 1 1 4.2 1.3c-.8 1.1-2 1.3-2 2.7m0 3h.01" /></svg>;
    case "pulse":
      return <svg {...shared}><path d="M3 12h4l3-8 4 16 3-8h4" /></svg>;
    case "clock":
      return <svg {...shared}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>;
    case "branch":
      return <svg {...shared}><circle cx="6" cy="4" r="2" /><circle cx="6" cy="20" r="2" /><circle cx="18" cy="16" r="2" /><path d="M6 6v12m0-9a7 7 0 0 0 7 7h3m-3-8h3a2 2 0 0 0 2-2V6" /></svg>;
    case "check":
      return <svg {...shared}><path d="m5 12 4 4L19 6" /></svg>;
    case "spark":
      return <svg {...shared}><path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z" /></svg>;
  }
}

const navigation: { label: string; icon: IconName; href?: string; active?: boolean; comingSoon?: boolean }[] = [
  { label: "Overview", icon: "overview", href: "#overview", active: true },
  { label: "Repositories", icon: "repository", href: "#codebases" },
  { label: "Developer Memory", icon: "memory", href: "#memory" },
  { label: "API Guardian", icon: "guardian", comingSoon: true },
];

const workspaces: {
  title: string;
  description: string;
  icon: IconName;
  accent: string;
  meta: string;
  href?: string;
  comingSoon?: boolean;
}[] = [
  { title: "Codebases", description: "Your repositories, understood.", icon: "code", accent: "mint", meta: "0 connected", href: "#codebases" },
  { title: "Q&A", description: "Explore code with context.", icon: "question", accent: "violet", meta: "Dev Recall", href: "#qa" },
  { title: "API Diagnostics", description: "Trace failures to their source.", icon: "pulse", accent: "amber", meta: "API Guardian", comingSoon: true },
  { title: "Developer Memory", description: "Keep decisions close to the code.", icon: "memory", accent: "blue", meta: "Dev Recall", href: "#memory" },
];

function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden="true">
      <svg viewBox="0 0 32 32" fill="none">
        <path d="M16 3.5 27 9.8v12.4L16 28.5 5 22.2V9.8L16 3.5Z" stroke="currentColor" strokeWidth="1.6" />
        <path d="m11.3 12.3-3.2 3.6 3.2 3.7M20.7 12.3l3.2 3.6-3.2 3.7M18 10.7l-4 10.6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}

function Sidebar() {
  return (
    <aside className="sidebar">
      <a className="brand" href="#overview" aria-label="DevPilot overview">
        <BrandMark />
        <span className="brand-name">dev<span>pilot</span></span>
        <span className="brand-beta">BETA</span>
      </a>

      <div className="side-label">WORKSPACE</div>
      <nav className="side-nav" aria-label="Main navigation">
        {navigation.map((item) => (
          item.comingSoon ? (
            <span key={item.label} className="nav-link nav-link-disabled" aria-disabled="true">
              <Icon name={item.icon} size={18} />
              <span>{item.label}</span>
              <span className="nav-coming-soon">Soon</span>
            </span>
          ) : (
            <a key={item.label} className={`nav-link${item.active ? " active" : ""}`} href={item.href} aria-current={item.active ? "page" : undefined}>
              <Icon name={item.icon} size={18} />
              <span>{item.label}</span>
              {item.label === "Repositories" && <span className="nav-count">0</span>}
            </a>
          )
        ))}
      </nav>

      <div className="side-label side-label-lower">PREFERENCES</div>
      <nav className="side-nav" aria-label="Preferences">
        <a className="nav-link" href="#settings"><Icon name="settings" size={18} /><span>Settings</span></a>
      </nav>

      <div className="sidebar-bottom">
        <div className="sidebar-help">
          <div className="help-icon"><Icon name="spark" size={17} /></div>
          <div><strong>Built for your flow</strong><span>Less context switching.<br />More time in the zone.</span></div>
        </div>
        <div className="profile-row">
          <div className="profile-avatar">DP</div>
          <div className="profile-copy"><strong>Dev workspace</strong><span>Free plan</span></div>
          <span className="profile-menu" aria-hidden="true">···</span>
        </div>
      </div>
    </aside>
  );
}

function WorkspaceCard({ item }: { item: (typeof workspaces)[number] }) {
  const contents = (
    <>
      <div className={`workspace-icon ${item.accent}`}><Icon name={item.icon} size={20} /></div>
      {item.comingSoon ? (
        <span className="coming-soon-label">Coming soon</span>
      ) : (
        <span className="card-arrow"><Icon name="arrow" size={16} /></span>
      )}
      <h3>{item.title}</h3>
      <p>{item.description}</p>
      <span className="workspace-meta">{item.meta}</span>
    </>
  );

  if (item.comingSoon) {
    return <article className="workspace-card workspace-card-disabled">{contents}</article>;
  }

  return <a className="workspace-card" href={item.href}>{contents}</a>;
}

export default function Home() {
  return (
    <div className="dashboard-shell">
      <Sidebar />
      <main className="main-panel" id="overview">
        <header className="topbar">
          <div className="breadcrumbs"><span>Workspace</span><span className="crumb-divider">/</span><strong>Overview</strong></div>
          <div className="topbar-actions">
            <span className="connection-status"><span className="status-dot" />Dashboard preview</span>
            <div className="top-avatar" aria-label="Dev workspace profile">D</div>
          </div>
        </header>

        <div className="dashboard-content">
          <section className="welcome-row" aria-labelledby="welcome-title">
            <div>
              <div className="eyebrow"><span className="eyebrow-line" />YOUR ENGINEERING WORKSPACE</div>
              <h1 id="welcome-title">Build with <span>context.</span></h1>
              <p className="welcome-copy">Your code, your decisions, your next move — all in one place.</p>
            </div>
            <div className="welcome-date"><span className="date-orb"><Icon name="spark" size={18} /></span><span>GOOD TO HAVE YOU HERE</span></div>
          </section>

          <RepositoryImportPanel />

          <section className="workspace-section" aria-labelledby="workspace-title">
            <div className="section-heading">
              <div><div className="section-eyebrow">YOUR TOOLKIT</div><h2 id="workspace-title">Workspace</h2></div>
              <span className="section-caption">Everything you need to move forward</span>
            </div>
            <div className="workspace-grid">
              {workspaces.map((item) => <WorkspaceCard key={item.title} item={item} />)}
            </div>
          </section>

          <section className="activity-section" aria-labelledby="activity-title">
            <div className="section-heading activity-heading">
              <div><div className="section-eyebrow">THE LATEST</div><h2 id="activity-title">Recent activity</h2></div>
            </div>
            <div className="activity-list" aria-live="polite">
              <p className="activity-empty">Your recent activity will appear here as you use DevPilot.</p>
            </div>
          </section>

          <footer className="dashboard-footer"><span>DEVPILOT <span className="footer-separator">/</span> ENGINEERING, IN SYNC</span><span>MADE FOR BUILDERS <span className="footer-spark">✳</span></span></footer>
        </div>
      </main>
    </div>
  );
}
