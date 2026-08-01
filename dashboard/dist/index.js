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
            "TRANSCRIPT_API_KEY is not configured — set it in Settings → Environment to enable fetching.")
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
                  h("th", { className: "yti-center" }, "Status")
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
  // Root page: Trends | Insights sub-tabs
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
        }, "Insights")
      ),
      view === "trends" ? h(TrendsView) : h(InsightsView)
    );
  }

  // -------------------------------------------------------------------------
  // Register
  // -------------------------------------------------------------------------

  if (window.__HERMES_PLUGINS__ && typeof window.__HERMES_PLUGINS__.register === "function") {
    window.__HERMES_PLUGINS__.register("youtube-insights", YouTubeInsightsPage);
  }
})();
