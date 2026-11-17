// DailyLetter-widget voor Scriptable (gratis in de App Store).
// Toont de eerste regels van je briefje op je beginscherm. Tik erop om het briefje te openen.
// Je gsm moet DailyLetter kunnen bereiken: zet Tailscale aan, of "VPN op aanvraag" in de Tailscale-app.

const ADDRESS = "__DAILYLETTER_URL__";
const LINES = { small: 2, medium: 3, large: 7, extraLarge: 7 };

async function load() {
  const request = new Request(ADDRESS + "/api/briefje");
  request.timeoutInterval = 15;
  return await request.loadJSON();
}

async function build() {
  const family = config.widgetFamily || "large";
  let data = null;
  try { data = await load(); } catch (error) { data = null; }

  const evening = data && data.version === "evening";
  const ink = new Color(evening ? "#EDE5D8" : "#2B2622");
  const quiet = new Color(evening ? "#A89C8C" : "#6E655C");
  const widget = new ListWidget();
  widget.backgroundColor = new Color(evening ? "#1C1916" : "#F5F1E8");
  widget.setPadding(14, 16, 14, 16);
  widget.url = ADDRESS + "/";

  const head = widget.addText(data ? [data.date_label, data.generated_label].filter(Boolean).join(" · ") : "DailyLetter");
  head.font = Font.systemFont(11);
  head.textColor = quiet;
  widget.addSpacer(8);

  const lines = !data ? ["Niet bereikbaar. Staat Tailscale aan?"]
    : data.lines.length ? data.lines.slice(0, LINES[family] || 3)
    : ["Er is vandaag nog geen briefje."];
  for (const line of lines) {
    const text = widget.addText(line);
    text.font = new Font("Georgia", family === "small" ? 13 : 15);
    text.textColor = data ? ink : quiet;
    text.lineLimit = family === "small" ? 4 : 3;
    text.minimumScaleFactor = 0.85;
    widget.addSpacer(6);
  }
  widget.addSpacer();
  // iOS decides the exact moment; this asks for a new look after half an hour at most.
  widget.refreshAfterDate = new Date(Date.now() + 30 * 60 * 1000);
  return widget;
}

const widget = await build();
if (config.runsInWidget) {
  Script.setWidget(widget);
} else {
  await widget.presentLarge();
}
Script.complete();
