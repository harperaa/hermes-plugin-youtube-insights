/**
 * youtube-insights — Hermes Dashboard Plugin
 *
 * Trends + Insights pages, ported from the original paperclip plugin with the
 * same layout, panels, and functions, restyled onto the hermes design system.
 *
 * Plain IIFE, no build step. Uses window.__HERMES_PLUGIN_SDK__ for React and
 * shared UI primitives; all backend calls go through SDK.fetchJSON so auth
 * works in both dashboard modes.
 */
(function () {
  "use strict";

  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK) return;

  const { React } = SDK;
  const h = React.createElement;
  const { useState, useEffect, useCallback } = SDK.hooks;
  const C = SDK.components || {};
  const Button = C.Button || function (p) { return h("button", p, p.children); };
  const Input = C.Input || function (p) { return h("input", p); };

  function api(path, options) {
    // Delegate to the host SDK's fetchJSON so auth is handled correctly in
    // BOTH dashboard modes (loopback token header / gated cookie). Never
    // hand-roll fetch or read window.__HERMES_SESSION_TOKEN__.
    return SDK.fetchJSON("/api/plugins/youtube-insights" + path, options);
  }

  // -------------------------------------------------------------------------
  // Helpers (ports of the original formatters)
  // -------------------------------------------------------------------------

  function formatNumber(n) {
    n = Number(n) || 0;
    if (n >= 1000000) return (n / 1000000).toFixed(1) + "M";
    if (n >= 1000) return (n / 1000).toFixed(1) + "K";
    return n.toLocaleString();
  }

  function formatDuration(seconds) {
    if (seconds == null) return "—";
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return m + ":" + String(s).padStart(2, "0");
  }

  function formatAgo(dateStr) {
    if (!dateStr) return "";
    const diff = Date.now() - new Date(dateStr).getTime();
    const hours = Math.floor(diff / 3600000);
    if (hours < 1) return "just now";
    if (hours < 24) return hours + "h ago";
    const days = Math.floor(hours / 24);
    if (days < 30) return days + "d ago";
    return Math.floor(days / 30) + "mo ago";
  }

  const CATEGORY_COLORS = {
    strategy: "#8b5cf6",
    technical: "#3b82f6",
    creativity: "#ec4899",
    productivity: "#22c55e",
    business: "#f59e0b",
    psychology: "#06b6d4",
    trend: "#ef4444",
    career: "#a855f7",
  };

  const INSIGHT_CATEGORIES = [
    "strategy", "technical", "creativity", "productivity",
    "business", "psychology", "trend", "career",
  ];

  const TREND_COLOR = {
    accelerating: "#22c55e",
    decelerating: "#ef4444",
    flat: "#9ca3af",
  };

  // -------------------------------------------------------------------------
  // Sparkline (port of src/ui/Sparkline.tsx)
  // -------------------------------------------------------------------------

  function Sparkline(props) {
    const points = props.points || [];
    const width = props.width || 80;
    const height = props.height || 30;
    if (points.length < 2) return null;
    const pad = 2;
    const min = Math.min.apply(null, points);
    const max = Math.max.apply(null, points);
    const range = max - min || 1;
    const coords = points
      .map(function (v, i) {
        const x = pad + (i / (points.length - 1)) * (width - 2 * pad);
        const y = height - pad - ((v - min) / range) * (height - 2 * pad);
        return x.toFixed(1) + "," + y.toFixed(1);
      })
      .join(" ");
    const color = TREND_COLOR[props.direction] || TREND_COLOR.flat;
    return h("svg", { width: width, height: height, className: "yti-sparkline" },
      h("polyline", { points: coords, fill: "none", stroke: color, strokeWidth: 2 })
    );
  }

  function TrendArrow(props) {
    const d = props.direction;
    const glyph = d === "accelerating" ? "↗" : d === "decelerating" ? "↘" : "→";
    return h("span", {
      className: "yti-trend-arrow",
      style: { color: TREND_COLOR[d] || TREND_COLOR.flat },
      title: d,
    }, glyph);
  }

  function StatCard(props) {
    return h("div", { className: "yti-stat-card" },
      h("div", { className: "yti-stat-value" }, props.value),
      h("div", { className: "yti-stat-label" }, props.label)
    );
  }

  // -------------------------------------------------------------------------
  // ✨ per-row generation cell (paperclip parity: idle sparkle → spinner
  // while the task is open → stale after 30 min (click re-runs) → done =
  // sparkle again + a fixed-slot ↗ to the worker's chat thread / task).
  // -------------------------------------------------------------------------
  function GenerateCell(props) {
    const v = props.video;
    const g = v.generation || null;
    const st = useState(false);
    const submitting = st[0], setSubmitting = st[1];
    const isOpen = !!g && g.status === "open";
    const isStale = !submitting && !!g && g.status === "stale";
    const isDone = !!g && g.status === "done";

    const label = isOpen
      ? "Script generation in progress — spinning until the task is done"
      : isStale
      ? "Previous attempt hasn't completed in 30+ min — click to re-run"
      : isDone
      ? "Re-generate (previous run completed — click ↗ to review)"
      : "Generate a similar-but-unique video script (creates a task + chat)";

    const onClick = function () {
      if (isOpen || submitting) return;
      setSubmitting(true);
      api("/generate-content", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ videoId: v.videoId }),
      }).then(function () { setSubmitting(false); props.refresh(); })
        .catch(function (e) { setSubmitting(false); window.alert(String((e && e.message) || e)); });
    };

    const chatHref = g && g.sessionId
      ? "/chat?resume=" + encodeURIComponent(g.sessionId) : null;
    const taskHref = g && g.taskId
      ? "/kanban#task=" + encodeURIComponent(g.taskId) : null;

    function navLink(href, text, title) {
      return h("a", {
        href: href,
        onClick: function (e) { e.preventDefault(); window.location.assign(href); },
        title: title,
        className: "yti-gen-link",
      }, text);
    }

    return h("span", { style: { display: "inline-flex", alignItems: "center", gap: 8 } },
      h("button", {
        className: "yti-generate-btn",
        onClick: onClick,
        disabled: isOpen || submitting,
        title: label,
        "aria-label": label,
        style: { cursor: (isOpen || submitting) ? "wait" : "pointer" },
      }, (isOpen || submitting)
        ? h("span", { className: "yti-gen-spinner", role: "status" })
        : h("span", { "aria-hidden": true }, "✨")),
      chatHref
        ? navLink(chatHref, "chat ↗", "Open this run's conversation thread")
        : null,
      taskHref
        ? navLink(taskHref, "task ↗", isDone
            ? "Finished run — scripts attached here and on the Artifacts tab"
            : "Open this run's kanban task")
        : null
    );
  }

  // -------------------------------------------------------------------------
  // Trends view (port of YouTubeTrendsPageContent)
  // -------------------------------------------------------------------------

  function TrendsView() {
    const [data, setData] = useState(null);
    const [channels, setChannels] = useState([]);
    const [newChannel, setNewChannel] = useState("");
    const [showChannels, setShowChannels] = useState(false);
    const [sortField, setSortField] = useState("vph");
    const [sortAsc, setSortAsc] = useState(false);
    const [fetching, setFetching] = useState(false);
    const [analyzing, setAnalyzing] = useState(false);
    const [notice, setNotice] = useState(null);

    const refresh = useCallback(function () {
      api("/videos").then(setData).catch(function (e) {
        setNotice({ tone: "error", text: String(e) });
      });
      api("/channels").then(function (d) {
        setChannels((d && d.channels) || []);
      }).catch(function () {});
    }, []);

    useEffect(function () { refresh(); }, [refresh]);

    // Poll while any ✨ generation task is open so the spinner flips to
    // ✨ + ↗ shortly after the worker completes (paperclip parity).
    const hasOpenGeneration = !!(data && data.videos || []).some(function (v) {
      return v.generation && v.generation.status === "open";
    });
    useEffect(function () {
      if (!hasOpenGeneration) return undefined;
      const id = window.setInterval(refresh, 15000);
      return function () { window.clearInterval(id); };
    }, [hasOpenGeneration, refresh]);

    const videos = (data && data.videos) || [];
    const loading = data === null;

    const handleFetch = function () {
      setFetching(true);
      setNotice(null);
      api("/fetch", { method: "POST" })
        .then(function (res) {
          if (res && res.error) {
            setNotice({ tone: "error", text: res.error });
            setFetching(false);
            return;
          }
          setNotice({ tone: "ok", text: "Fetch started — new videos will appear as they're downloaded (~30-90s)." });
          // Poll for ~2 minutes to surface rows as the background fetch lands.
          let ticks = 0;
          const id = window.setInterval(function () {
            ticks += 1;
            refresh();
            if (ticks >= 8) {
              window.clearInterval(id);
              setFetching(false);
            }
          }, 15000);
        })
        .catch(function (e) {
          setNotice({ tone: "error", text: String(e) });
          setFetching(false);
        });
    };

    const handleAnalyze = function () {
      setAnalyzing(true);
      setNotice(null);
      api("/trigger-analysis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      })
        .then(function (res) {
          const n = (res && res.triggered) || 0;
          setNotice({
            tone: "ok",
            text: n
              ? "Queued " + n + " video(s) for analysis. Run the cron job or ask the agent to work the queue (yt_trigger_analysis)."
              : "Nothing to analyze — every transcribed video is already queued or analyzed.",
          });
          refresh();
        })
        .catch(function (e) { setNotice({ tone: "error", text: String(e) }); })
        .finally(function () { setAnalyzing(false); });
    };

    const handleAddChannel = function (e) {
      e.preventDefault();
      const handle = newChannel.trim();
      if (!handle) return;
      api("/channels", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ handle: handle }),
      }).then(function (d) {
        setChannels((d && d.channels) || []);
        setNewChannel("");
      }).catch(function (e2) { setNotice({ tone: "error", text: String(e2) }); });
    };

    const handleRemoveChannel = function (handle) {
      api("/channels/" + encodeURIComponent(handle), { method: "DELETE" })
        .then(function (d) { setChannels((d && d.channels) || []); })
        .catch(function () {});
    };

    const toggleSort = function (field) {
      if (sortField === field) setSortAsc(!sortAsc);
      else { setSortField(field); setSortAsc(false); }
    };

    const sorted = videos.slice().sort(function (a, b) {
      const mul = sortAsc ? 1 : -1;
      if (sortField === "vph") return (a.vph - b.vph) * mul;
      if (sortField === "views") return (a.views - b.views) * mul;
      return (new Date(a.published).getTime() - new Date(b.published).getTime()) * mul;
    });

    const topVph = videos.length
      ? Math.max.apply(null, videos.map(function (v) { return v.vph; }))
      : 0;

    const sortGlyph = function (field) {
      if (sortField !== field) return field === "vph" ? " ↓" : "";
      return sortAsc ? " ▲" : " ▼";
    };

    return h("div", { className: "yti-page" },
      h("div", { className: "yti-header" },
        h("h1", { className: "yti-title" }, "YouTube Trends"),
        h("div", { className: "yti-header-actions" },
          h(Button, { size: "sm", disabled: analyzing, onClick: handleAnalyze },
            analyzing ? "Queuing…" : "Analyze"),
          h(Button, { size: "sm", disabled: fetching, onClick: handleFetch },
            fetching ? "Fetching…" : "Refresh")
        )
      ),
      h("div", { className: "yti-subtle" },
        videos.length + " videos",
        data && data.lastFetchRun
          ? " · last fetch " + formatAgo(data.lastFetchRun)
          : ""
      ),
      notice ? h("div", {
        className: "yti-notice " + (notice.tone === "error" ? "yti-notice-error" : "yti-notice-ok"),
      }, notice.text) : null,
      data && data.hasApiKey === false
        ? h("div", { className: "yti-notice yti-notice-error" },
            "TRANSCRIPT_API_KEY is not configured — create a key at ",
            h("a", { href: "https://transcriptapi.com", target: "_blank", rel: "noreferrer" }, "transcriptapi.com"),
            ", then set it on the ",
            h("a", { href: "/env" }, "Keys page"),
            " (Custom Keys → TRANSCRIPT_API_KEY) to enable fetching.")
        : null,

      // Stats
      h("div", { className: "yti-stats-row" },
        h(StatCard, { value: String(videos.length), label: "Videos Tracked" }),
        h(StatCard, { value: String(channels.length), label: "Channels" }),
        h(StatCard, { value: formatNumber(topVph), label: "Top VPH" })
      ),

      // Channel management
      h("div", { className: "yti-card yti-channels-card" },
        h("div", {
          className: "yti-channels-toggle",
          onClick: function () { setShowChannels(!showChannels); },
        }, (showChannels ? "▼" : "▶") + " Tracked Channels (" + channels.length + ")"),
        showChannels ? h("div", { className: "yti-channels-body" },
          h("div", { className: "yti-chip-row" },
            channels.map(function (ch) {
              return h("span", { key: ch, className: "yti-chip yti-chip-channel" },
                ch,
                h("span", {
                  className: "yti-chip-remove",
                  title: "Stop tracking " + ch,
                  onClick: function () { handleRemoveChannel(ch); },
                }, "✕")
              );
            })
          ),
          h("form", { className: "yti-add-channel", onSubmit: handleAddChannel },
            h(Input, {
              value: newChannel,
              placeholder: "@ChannelHandle",
              onChange: function (e) { setNewChannel(e.target.value); },
            }),
            h(Button, { size: "sm", type: "submit" }, "Add")
          )
        ) : null
      ),

      // Video table
      loading
        ? h("div", { className: "yti-empty" }, "Loading…")
        : h("div", { className: "yti-table-wrap" },
            h("table", { className: "yti-table" },
              h("thead", null,
                h("tr", null,
                  h("th", null, "Thumbnail"),
                  h("th", null, "Title"),
                  h("th", null, "Channel"),
                  h("th", {
                    className: "yti-sortable",
                    onClick: function () { toggleSort("published"); },
                  }, "Published" + sortGlyph("published")),
                  h("th", { className: "yti-right" }, "Duration"),
                  h("th", {
                    className: "yti-right yti-sortable",
                    onClick: function () { toggleSort("views"); },
                  }, "Views" + sortGlyph("views")),
                  h("th", {
                    className: "yti-right yti-sortable yti-strong",
                    onClick: function () { toggleSort("vph"); },
                  }, "VPH" + sortGlyph("vph")),
                  h("th", { className: "yti-center" }, "Trend"),
                  h("th", { className: "yti-center" }, "Status"),
                  h("th", { className: "yti-center", title: "Generate a similar-but-unique script from this video" }, "Create")
                )
              ),
              h("tbody", null,
                sorted.map(function (v) {
                  return h("tr", { key: v.videoId },
                    h("td", null,
                      h("a", { href: v.link, target: "_blank", rel: "noopener" },
                        v.thumbnail
                          ? h("img", { className: "yti-thumb", src: v.thumbnail, alt: "" })
                          : h("div", { className: "yti-thumb yti-thumb-empty" })
                      )
                    ),
                    h("td", null,
                      h("a", {
                        className: "yti-video-link",
                        href: v.link, target: "_blank", rel: "noopener",
                      }, v.title)
                    ),
                    h("td", { className: "yti-muted" }, v.author),
                    h("td", { className: "yti-muted" }, formatAgo(v.published)),
                    h("td", { className: "yti-right yti-muted" }, formatDuration(v.duration)),
                    h("td", { className: "yti-right" }, formatNumber(v.views)),
                    h("td", { className: "yti-right yti-strong" }, formatNumber(v.vph)),
                    h("td", { className: "yti-center" },
                      h("div", null,
                        h(TrendArrow, { direction: v.trendDirection }),
                        h(Sparkline, { points: v.sparklinePoints, direction: v.trendDirection })
                      ),
                      h("div", { className: "yti-pts" }, v.snapshotCount + " pts")
                    ),
                    h("td", { className: "yti-center" },
                      h("span", { className: "yti-status yti-status-" + (v.status || "discovered") },
                        v.status || "discovered")
                    ),
                    h("td", { className: "yti-center" },
                      h(GenerateCell, { video: v, refresh: refresh })
                    )
                  );
                })
              )
            ),
            sorted.length === 0
              ? h("div", { className: "yti-empty" },
                  "No videos tracked yet. Add channels above and click Refresh.")
              : null
          )
    );
  }

  // -------------------------------------------------------------------------
  // Insights view (port of InsightsPageContent)
  // -------------------------------------------------------------------------

  function InsightsView() {
    const [search, setSearch] = useState("");
    const [category, setCategory] = useState("");
    const [sortBy, setSortBy] = useState("sources");
    const [expandedId, setExpandedId] = useState(null);
    const [page, setPage] = useState(0);
    const [listData, setListData] = useState(null);
    const [stats, setStats] = useState(null);
    const limit = 30;

    const load = useCallback(function () {
      const params = new URLSearchParams({
        q: search, category: category, sortBy: sortBy,
        limit: String(limit), offset: String(page * limit),
      });
      api("/insights?" + params.toString()).then(setListData).catch(function () {
        setListData({ insights: [], total: 0 });
      });
    }, [search, category, sortBy, page]);

    useEffect(function () {
      const id = window.setTimeout(load, search ? 250 : 0);
      return function () { window.clearTimeout(id); };
    }, [load, search]);

    useEffect(function () {
      api("/insights/stats").then(setStats).catch(function () {});
    }, []);

    const insights = (listData && listData.insights) || [];
    const total = (listData && listData.total) || 0;
    const st = stats || { totalInsights: 0, totalSources: 0, topInsight: null, categories: {} };
    const loading = listData === null;

    const handleDelete = function (insight) {
      if (!window.confirm("Delete this insight?")) return;
      api("/insights/" + encodeURIComponent(insight.id), { method: "DELETE" })
        .then(function () {
          load();
          api("/insights/stats").then(setStats).catch(function () {});
        })
        .catch(function () {});
    };

    return h("div", { className: "yti-page yti-page-narrow" },
      h("h1", { className: "yti-title yti-title-block" }, "YouTube Insights"),

      // Stats
      h("div", { className: "yti-stats-row" },
        h(StatCard, { value: String(st.totalInsights), label: "Total Insights" }),
        h(StatCard, { value: String(st.totalSources), label: "Sources Analyzed" }),
        st.topInsight ? h("div", { className: "yti-stat-card yti-stat-top" },
          h("div", { className: "yti-stat-top-text" },
            st.topInsight.text.slice(0, 60) + "…"),
          h("div", { className: "yti-stat-label" },
            "Top Insight (" + st.topInsight.sourceCount + " sources)")
        ) : null
      ),

      // Search / filter
      h("div", { className: "yti-filter-row" },
        h(Input, {
          className: "yti-search",
          value: search,
          placeholder: "Search insights...",
          onChange: function (e) { setSearch(e.target.value); setPage(0); },
        }),
        h("select", {
          className: "yti-select",
          value: category,
          onChange: function (e) { setCategory(e.target.value); setPage(0); },
        },
          h("option", { value: "" }, "All Categories"),
          INSIGHT_CATEGORIES.map(function (c) {
            return h("option", { key: c, value: c }, c);
          })
        ),
        h("select", {
          className: "yti-select",
          value: sortBy,
          onChange: function (e) { setSortBy(e.target.value); },
        },
          h("option", { value: "sources" }, "Most Sourced"),
          h("option", { value: "recent" }, "Most Recent")
        )
      ),

      // Insight cards
      loading
        ? h("div", { className: "yti-empty" }, "Loading…")
        : h("div", null,
            insights.map(function (insight) {
              const expanded = expandedId === insight.id;
              return h("div", { key: insight.id, className: "yti-card yti-insight-card" },
                h("div", { className: "yti-insight-head" },
                  h("div", { className: "yti-insight-main" },
                    h("div", {
                      className: "yti-insight-text",
                      onClick: function () {
                        setExpandedId(expanded ? null : insight.id);
                      },
                    }, insight.text),
                    insight.detail && !expanded
                      ? h("div", { className: "yti-insight-preview" },
                          insight.detail.slice(0, 120) + "…")
                      : null,
                    h("div", { className: "yti-insight-meta" },
                      h("span", {
                        className: "yti-chip",
                        style: { background: CATEGORY_COLORS[insight.category] || "#666" },
                      }, insight.category),
                      h("span", { className: "yti-muted yti-small" },
                        insight.sourceCount + " source" + (insight.sourceCount !== 1 ? "s" : "")),
                      h("span", { className: "yti-faint yti-small" },
                        formatAgo(insight.lastSeen))
                    )
                  ),
                  h(Button, {
                    size: "sm",
                    className: "yti-delete-btn",
                    onClick: function () { handleDelete(insight); },
                  }, "Delete")
                ),
                expanded ? h("div", { className: "yti-insight-expanded" },
                  insight.detail
                    ? h("div", { className: "yti-insight-detail" }, insight.detail)
                    : null,
                  (insight.sourceContexts && insight.sourceContexts.length)
                    ? insight.sourceContexts.map(function (src, i) {
                        const tsSuffix = src.timestampRef
                          ? "&t=" + src.timestampRef.replace(":", "m") + "s"
                          : "";
                        return h("div", { key: i, className: "yti-source" },
                          h("div", { className: "yti-small" },
                            h("a", {
                              className: "yti-source-link",
                              href: src.sourceUrl + tsSuffix,
                              target: "_blank", rel: "noopener",
                            }, src.title || src.sourceUrl),
                            src.author
                              ? h("span", { className: "yti-muted" }, " — " + src.author)
                              : null,
                            src.timestampRef
                              ? h("span", { className: "yti-muted yti-ts" },
                                  "[" + src.timestampRef + "]")
                              : null
                          ),
                          src.context
                            ? h("div", { className: "yti-source-quote" },
                                "“" + src.context + "”")
                            : null
                        );
                      })
                    : h("div", { className: "yti-faint yti-small" },
                        "No source details available")
                ) : null
              );
            }),
            insights.length === 0
              ? h("div", { className: "yti-empty" },
                  "No insights found. Run analysis on tracked videos to generate insights.")
              : null,
            total > limit ? h("div", { className: "yti-pagination" },
              h(Button, {
                size: "sm", disabled: page === 0,
                onClick: function () { setPage(page - 1); },
              }, "Previous"),
              h("span", { className: "yti-muted yti-small" },
                (page * limit + 1) + "–" + Math.min((page + 1) * limit, total) + " of " + total),
              h(Button, {
                size: "sm", disabled: (page + 1) * limit >= total,
                onClick: function () { setPage(page + 1); },
              }, "Next")
            ) : null
          )
    );
  }


  // -------------------------------------------------------------------------
  // Markdown renderer (same approach as the value-creator plugin's bundle)
  // -------------------------------------------------------------------------

  function mdInline(text, keyBase) {
    var out = [];
    var rest = String(text);
    var key = 0;
    var re = /(\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)|\*([^*]+)\*)/;
    while (rest.length) {
      var m = re.exec(rest);
      if (!m) { out.push(rest); break; }
      if (m.index > 0) out.push(rest.slice(0, m.index));
      var k = keyBase + "-" + key++;
      if (m[2] != null) out.push(h("strong", { key: k }, m[2]));
      else if (m[3] != null) out.push(h("code", { key: k }, m[3]));
      else if (m[4] != null)
        out.push(h("a", { key: k, href: m[5], target: "_blank", rel: "noreferrer" }, m[4]));
      else if (m[6] != null) out.push(h("em", { key: k }, m[6]));
      rest = rest.slice(m.index + m[1].length);
    }
    return out;
  }

  function splitTableRow(line) {
    var t = line.trim().replace(/^\|/, "").replace(/\|$/, "");
    return t.split("|").map(function (c) { return c.trim(); });
  }

  function isTableDivider(line) {
    return /^\s*\|?\s*:?-{2,}.*\|/.test(line) && /^[\s|:-]+$/.test(line);
  }

  function renderMarkdown(md) {
    var lines = String(md || "").split(/\r?\n/);
    var blocks = [];
    var i = 0;
    var key = 0;
    while (i < lines.length) {
      var line = lines[i];
      if (!line.trim()) { i++; continue; }
      if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
        blocks.push(h("hr", { key: "k" + key++, className: "yti-md-hr" }));
        i++;
        continue;
      }
      var hm = /^(#{1,6})\s+(.*)$/.exec(line);
      if (hm) {
        blocks.push(h("h" + Math.min(6, hm[1].length + 1), { key: "k" + key++ },
          mdInline(hm[2], "h" + key)));
        i++;
        continue;
      }
      if (/^```/.test(line)) {
        var code = [];
        i++;
        while (i < lines.length && !/^```/.test(lines[i])) { code.push(lines[i]); i++; }
        i++;
        blocks.push(h("pre", { key: "k" + key++ }, h("code", null, code.join("\n"))));
        continue;
      }
      if (line.indexOf("|") >= 0 && i + 1 < lines.length && isTableDivider(lines[i + 1])) {
        var headCells = splitTableRow(line);
        i += 2;
        var rows = [];
        while (i < lines.length && lines[i].indexOf("|") >= 0 && lines[i].trim()) {
          rows.push(splitTableRow(lines[i]));
          i++;
        }
        blocks.push(
          h("table", { key: "k" + key++ },
            h("thead", null, h("tr", null, headCells.map(function (c, ci) {
              return h("th", { key: ci }, mdInline(c, "th" + ci));
            }))),
            h("tbody", null, rows.map(function (r, ri) {
              return h("tr", { key: ri }, r.map(function (c, ci) {
                return h("td", { key: ci }, mdInline(c, "td" + ri + "-" + ci));
              }));
            }))
          )
        );
        continue;
      }
      if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
        var ordered = /^\s*\d+\./.test(line);
        var items = [];
        while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
          items.push(lines[i].replace(/^\s*([-*]|\d+\.)\s+/, ""));
          i++;
        }
        blocks.push(
          h(ordered ? "ol" : "ul", { key: "k" + key++ }, items.map(function (it, ii) {
            return h("li", { key: ii }, mdInline(it, "li" + ii));
          }))
        );
        continue;
      }
      var para = [];
      while (i < lines.length && lines[i].trim() && !/^(#{1,6})\s|^```|^\s*([-*]|\d+\.)\s+/.test(lines[i]) &&
             !(lines[i].indexOf("|") >= 0 && i + 1 < lines.length && isTableDivider(lines[i + 1]))) {
        para.push(lines[i]);
        i++;
      }
      blocks.push(h("p", { key: "k" + key++ }, mdInline(para.join(" "), "p" + key)));
    }
    return h("div", { className: "yti-md" }, blocks);
  }

  // -------------------------------------------------------------------------
  // Artifacts view — port of the original Workspace Deliverables page
  // -------------------------------------------------------------------------

  var FILE_ICONS = {
    ".md": "📝", ".txt": "📄", ".json": "🔧", ".csv": "🔢",
    ".png": "🖼", ".jpg": "🖼", ".jpeg": "🖼", ".webp": "🖼", ".gif": "🖼",
    ".pdf": "📕",
  };

  function TreeEntry(props) {
    var node = props.node;
    var depth = props.depth || 0;
    var openState = useState(depth < 2);
    var open = openState[0], setOpen = openState[1];
    if (node.kind === "dir") {
      return h("div", { className: "yti-tree-dir" },
        h("div", {
          className: "yti-tree-row",
          style: { paddingLeft: (depth * 14) + "px" },
          onClick: function () { setOpen(!open); },
        },
          h("span", { className: "yti-tree-caret" }, open ? "▾" : "▸"),
          h("span", { className: "yti-tree-name" }, "📁 " + node.name)
        ),
        open ? (node.children || []).map(function (c) {
          return h(TreeEntry, { key: c.relPath, node: c, depth: depth + 1,
                                selected: props.selected, onSelect: props.onSelect });
        }) : null
      );
    }
    var active = props.selected === node.relPath;
    return h("div", {
      className: "yti-tree-row yti-tree-file" + (active ? " yti-tree-active" : ""),
      style: { paddingLeft: (depth * 14 + 16) + "px" },
      onClick: function () { props.onSelect(node); },
    },
      h("span", { className: "yti-tree-name" },
        (FILE_ICONS[node.ext] || "📄") + " " + node.name),
      h("span", { className: "yti-tree-size" }, formatNumber(node.size) + "B")
    );
  }

  function ArtifactsView() {
    var treeState = useState(null);
    var tree = treeState[0], setTree = treeState[1];
    var selState = useState(null);
    var sel = selState[0], setSel = selState[1];
    var fileState = useState(null);
    var file = fileState[0], setFile = fileState[1];
    var editState = useState(null); // null = viewing; string = editing buffer
    var editing = editState[0], setEditing = editState[1];
    var busyState = useState(false);
    var busy = busyState[0], setBusy = busyState[1];
    var pdfUrlState = useState(null);
    var pdfUrl = pdfUrlState[0], setPdfUrl = pdfUrlState[1];
    var qState = useState("");
    var q = qState[0], setQ = qState[1];
    var imgState = useState(false);
    var withImages = imgState[0], setWithImages = imgState[1];
    var sortState = useState(true); // newest-first by default
    var sortDesc = sortState[0], setSortDesc = sortState[1];
    var prodState = useState({});
    var produce = prodState[0], setProduce = prodState[1];
    var copiedState = useState("");
    var copied = copiedState[0], setCopied = copiedState[1];

    var loadTree = useCallback(function () {
      api("/workspace/tree").then(function (d) { setTree(d.tree || []); })
        .catch(function () { setTree([]); });
      api("/produce-states").then(function (d) { setProduce((d && d.states) || {}); })
        .catch(function () {});
    }, []);
    useEffect(function () { loadTree(); }, [loadTree]);

    // Poll while any produce run is open so the spinner resolves on its own.
    var hasOpenProduce = Object.keys(produce).some(function (k) {
      return produce[k] && produce[k].status === "open";
    });
    useEffect(function () {
      if (!hasOpenProduce) return undefined;
      var id = window.setInterval(loadTree, 15000);
      return function () { window.clearInterval(id); };
    }, [hasOpenProduce, loadTree]);

    useEffect(function () {
      setEditing(null);
      setFile(null);
      setCopied("");
      if (pdfUrl) { URL.revokeObjectURL(pdfUrl); setPdfUrl(null); }
      if (!sel) return;
      if (sel.ext === ".pdf") {
        SDK.authedFetch("/api/plugins/youtube-insights/workspace/file?path=" +
                        encodeURIComponent(sel.relPath))
          .then(function (r) { return r.json(); })
          .then(function (d) {
            var bytes = atob(d.base64 || "");
            var arr = new Uint8Array(bytes.length);
            for (var i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
            var url = URL.createObjectURL(new Blob([arr], { type: "application/pdf" }));
            setPdfUrl(url);
            setFile(d);
          })
          .catch(function () { setFile({ ok: false, error: "Could not load PDF." }); });
        return;
      }
      api("/workspace/file?path=" + encodeURIComponent(sel.relPath))
        .then(setFile)
        .catch(function (e) { setFile({ ok: false, error: String(e && e.message || e) }); });
    }, [sel && sel.relPath]);

    function save() {
      if (editing == null || !sel) return;
      setBusy(true);
      api("/workspace/file", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: sel.relPath, content: editing }),
      }).then(function () {
        setBusy(false);
        setFile(Object.assign({}, file, { text: editing }));
        setEditing(null);
      }).catch(function (e) {
        setBusy(false);
        alert("Save failed: " + (e && e.message || e));
      });
    }

    function copyMarkdown() {
      if (!file || file.kind !== "text") return;
      navigator.clipboard.writeText(file.text || "").then(function () {
        setCopied("md"); window.setTimeout(function () { setCopied(""); }, 1500);
      }).catch(function () { alert("Clipboard unavailable"); });
    }

    function copyRich() {
      if (!file || file.kind !== "text") return;
      var el = document.querySelector(".yti-md-rendered");
      var html = el ? el.innerHTML : "";
      var write = (window.ClipboardItem && html)
        ? navigator.clipboard.write([new window.ClipboardItem({
            "text/html": new Blob([html], { type: "text/html" }),
            "text/plain": new Blob([file.text || ""], { type: "text/plain" }),
          })])
        : navigator.clipboard.writeText(file.text || "");
      write.then(function () {
        setCopied("rich"); window.setTimeout(function () { setCopied(""); }, 1500);
      }).catch(function () { alert("Clipboard unavailable"); });
    }

    function produceScript() {
      if (!sel) return;
      api("/produce", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: sel.relPath }),
      }).then(function () { loadTree(); })
        .catch(function (e) { alert(String((e && e.message) || e)); });
    }

    function flattenFiles(nodes, out) {
      nodes.forEach(function (n) {
        if (n.kind === "file") out.push(n);
        if (n.children) flattenFiles(n.children, out);
      });
      return out;
    }

    function formatMtime(iso) {
      try {
        var d = new Date(iso);
        return "last modified " + d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) +
          ", " + d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
      } catch (e) { return ""; }
    }

    var preview;
    if (!sel) {
      preview = h("div", { className: "yti-empty" },
        "Select a file to preview it. Pipeline outputs land under ",
        h("code", null, "youtube/{date}/recommended/"),
        " — concepts, scripts, and generated assets.");
    } else if (!file) {
      preview = h("div", { className: "yti-empty" }, "Loading…");
    } else if (file.ok === false) {
      preview = h("div", { className: "yti-empty yti-error" }, file.error || "Could not read file.");
    } else if (sel.ext === ".pdf") {
      preview = pdfUrl
        ? h("object", { data: pdfUrl, type: "application/pdf", className: "yti-pdf" },
            h("a", { href: pdfUrl, download: sel.name }, "Download " + sel.name))
        : h("div", { className: "yti-empty" }, "Loading PDF…");
    } else if (file.kind === "binary" && (file.mimeType || "").indexOf("image/") === 0) {
      preview = h("img", {
        className: "yti-artifact-img",
        src: "data:" + file.mimeType + ";base64," + file.base64,
        alt: sel.name,
      });
    } else if (file.kind === "text" && sel.ext === ".md") {
      // Markdown previews rendered by default (paperclip deliverables parity)
      preview = editing != null
        ? h("textarea", {
            className: "yti-md-editor", value: editing,
            onChange: function (e) { setEditing(e.target.value); },
          })
        : h("div", { className: "yti-md yti-md-rendered" }, renderMarkdown(file.text));
    } else if (file.kind === "text") {
      preview = editing != null
        ? h("textarea", {
            className: "yti-md-editor", value: editing,
            onChange: function (e) { setEditing(e.target.value); },
          })
        : h("pre", { className: "yti-pre" }, file.text);
    } else {
      preview = h("div", { className: "yti-empty" }, "No preview for " + sel.ext + " files.");
    }

    var canEdit = sel && file && file.kind === "text" &&
      [".md", ".txt", ".json", ".yml", ".yaml", ".csv"].indexOf(sel.ext) >= 0;
    var isScript = sel && sel.ext === ".md" && /script/i.test(sel.name);
    var prod = sel && produce[sel.relPath];
    var prodOpen = !!prod && prod.status === "open";
    var prodChat = prod && prod.sessionId
      ? "/chat?resume=" + encodeURIComponent(prod.sessionId) : null;
    var prodTask = prod && prod.taskId
      ? "/kanban#task=" + encodeURIComponent(prod.taskId) : null;

    // Preview header (paperclip deliverables parity): path · mtime · actions
    var previewHead = sel ? h("div", { className: "yti-preview-head" },
      h("code", { className: "yti-preview-path" }, sel.relPath),
      h("span", { className: "yti-preview-actions" },
        (file && file.mtime) ? h("span", { className: "yti-mtime" }, formatMtime(file.mtime)) : null,
        isScript ? h(Button, {
          size: "sm",
          disabled: prodOpen,
          title: prodOpen
            ? "Producing — images, thumbnails, and PDF are being generated"
            : "Generate all beat images, 3 thumbnails, and the production PDF into this script's assets folder",
          onClick: produceScript,
          className: "yti-produce-btn",
        }, prodOpen ? "Producing…" : "Produce 🎥") : null,
        prodChat ? h("a", { className: "yti-gen-link", href: prodChat,
          onClick: function (e) { e.preventDefault(); window.location.assign(prodChat); } }, "chat ↗") : null,
        prodTask ? h("a", { className: "yti-gen-link", href: prodTask,
          onClick: function (e) { e.preventDefault(); window.location.assign(prodTask); } }, "task ↗") : null,
        canEdit ? (editing != null
          ? [h(Button, { key: "save", size: "sm", disabled: busy, onClick: save }, busy ? "Saving…" : "Save"),
             h(Button, { key: "cancel", size: "sm", variant: "outline",
               onClick: function () { setEditing(null); } }, "Cancel")]
          : h(Button, { size: "sm", variant: "outline",
              onClick: function () { setEditing(file && file.text || ""); } }, "Edit")) : null,
        (file && file.kind === "text")
          ? h(Button, { size: "sm", variant: "outline", onClick: copyMarkdown },
              copied === "md" ? "Copied!" : "Copy Markdown") : null,
        (file && file.kind === "text" && sel.ext === ".md")
          ? h(Button, { size: "sm", variant: "outline", onClick: copyRich },
              copied === "rich" ? "Copied!" : "Copy Rich") : null
      )
    ) : null;

    // Recursive sort: directories first, then names — descending by default
    // so date-named folders (YYYY-MM-DD) put the newest work on top.
    function sortTree(nodes) {
      var copy = nodes.slice().map(function (n) {
        return n.children ? Object.assign({}, n, { children: sortTree(n.children) }) : n;
      });
      copy.sort(function (a, b) {
        if ((a.kind === "dir") !== (b.kind === "dir")) return a.kind === "dir" ? -1 : 1;
        var cmp = a.name.toLowerCase() < b.name.toLowerCase() ? -1
          : a.name.toLowerCase() > b.name.toLowerCase() ? 1 : 0;
        return sortDesc && a.kind === "dir" && b.kind === "dir" ? -cmp : cmp;
      });
      return copy;
    }

    var IMG_EXTS = [".png", ".jpg", ".jpeg", ".webp", ".gif"];
    var query = q.trim().toLowerCase();
    var results = (query || withImages) && tree
      ? flattenFiles(tree, []).filter(function (n) {
          if (query && n.relPath.toLowerCase().indexOf(query) === -1) return false;
          if (withImages && IMG_EXTS.indexOf(n.ext) === -1) return false;
          return true;
        })
      : null;

    return h("div", { className: "yti-artifacts" },
      h("div", { className: "yti-artifacts-head" },
        h("h2", null, "Workspace Deliverables"),
        h("div", { className: "yti-actions" },
          h(Button, { size: "sm", variant: "outline", onClick: loadTree }, "Refresh")
        )
      ),
      h("div", { className: "yti-artifacts-body" },
        h("div", { className: "yti-tree" },
          h("div", { className: "yti-tree-tools" },
            h("input", {
              className: "yti-artifact-search",
              placeholder: "Search filenames…",
              value: q,
              onChange: function (e) { setQ(e.target.value); },
            }),
            h("div", { className: "yti-tree-chips" },
              h("button", {
                className: "yti-filter-chip" + (withImages ? " yti-filter-chip-on" : ""),
                onClick: function () { setWithImages(!withImages); },
                title: "Show only image files (generated assets and thumbnails)",
              }, "With Images"),
              h("button", {
                className: "yti-filter-chip",
                onClick: function () { setSortDesc(!sortDesc); },
                title: "Toggle directory sort order",
              }, sortDesc ? "Newest first ↓" : "Oldest first ↑"))
          ),
          tree == null ? h("div", { className: "yti-empty" }, "Loading…")
          : results !== null
            ? (results.length === 0
                ? h("div", { className: "yti-empty" }, "No files match \u201C" + q + "\u201D.")
                : results.map(function (n) {
                    return h("button", {
                      key: n.relPath,
                      className: "yti-tree-file yti-search-hit" +
                        (sel && sel.relPath === n.relPath ? " yti-tree-active" : ""),
                      onClick: function () { setSel(n); },
                      title: n.relPath,
                    }, n.relPath);
                  }))
          : tree.length === 0
            ? h("div", { className: "yti-empty" },
                "No deliverables yet. The scheduled pipeline writes concepts and ",
                "scripts to ", h("code", null, "youtube/{date}/recommended/"), ".")
            : sortTree(tree).map(function (n) {
                return h(TreeEntry, { key: n.relPath, node: n, depth: 0,
                  selected: sel && sel.relPath,
                  onSelect: function (node) { setSel(node); } });
              })
        ),
        h("div", { className: "yti-preview" },
          previewHead,
          preview)
      )
    );
  }

  // -------------------------------------------------------------------------
  // Root page: Trends | Insights | Artifacts sub-tabs
  // -------------------------------------------------------------------------

  function YouTubeInsightsPage() {
    const [view, setView] = useState("trends");
    return h("div", { className: "yti-root" },
      h("div", { className: "yti-tabs" },
        h("button", {
          className: "yti-tab" + (view === "trends" ? " yti-tab-active" : ""),
          onClick: function () { setView("trends"); },
        }, "Trends"),
        h("button", {
          className: "yti-tab" + (view === "insights" ? " yti-tab-active" : ""),
          onClick: function () { setView("insights"); },
        }, "Insights"),
        h("button", {
          className: "yti-tab" + (view === "artifacts" ? " yti-tab-active" : ""),
          onClick: function () { setView("artifacts"); },
        }, "Artifacts")
      ),
      view === "trends" ? h(TrendsView)
        : view === "insights" ? h(InsightsView)
        : h(ArtifactsView)
    );
  }

  // -------------------------------------------------------------------------
  // Register
  // -------------------------------------------------------------------------

  if (window.__HERMES_PLUGINS__ && typeof window.__HERMES_PLUGINS__.register === "function") {
    window.__HERMES_PLUGINS__.register("youtube-insights", YouTubeInsightsPage);
  }
})();
