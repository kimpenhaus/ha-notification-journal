// Made-up household for the README screenshots: Alex and Sam, no real data.
(() => {
  const avatar = (bg, fg) =>
    "data:image/svg+xml," +
    encodeURIComponent(
      `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'><rect width='40' height='40' fill='${bg}'/><circle cx='20' cy='16' r='7' fill='${fg}'/><ellipse cx='20' cy='36' rx='13' ry='10' fill='${fg}'/></svg>`,
    );
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const at = (dayOffset, h, m) => new Date(today.getTime() + dayOffset * 86400000 + (h * 60 + m) * 60000).toISOString();
  const alex = { kind: "person", id: "person.alex", name: "Alex", picture: avatar("#00796b", "#b2dfdb"), user_id: "user-alex" };
  const sam = { kind: "person", id: "person.sam", name: "Sam", picture: avatar("#5e35b1", "#d1c4e9"), user_id: "user-sam" };
  const automation = (id, name) => ({ kind: "automation", entity_id: `automation.${id}`, name, trace_key: `automation.${id}`, run_id: "r1", user_id: null });
  const system = { kind: "system", entity_id: null, name: null, trace_key: null, run_id: null, user_id: null };
  const everyone = { kind: "everyone", id: "persistent_notification", name: "Home Assistant", picture: null, user_id: null };
  const speaker = (id, name) => ({ kind: "speaker", id: `media_player.${id}`, name, picture: null, user_id: null });
  const base = { data: null, error: null, group: null, inner_calls: [], trace_path: "/config/automation/trace/x", source_ref: null, status_time: null, status_by: null, status: "sent", context_id: "c", answers: [] };
  const integration = (domain, name) => ({ kind: "integration", entity_id: null, name, integration: domain, trace_key: null, run_id: null, user_id: null });
  const family = {
    group: "notify.family",
    recipients: [alex, sam],
    inner_calls: [
      { channel: "notify.mobile_app_alex_phone", recipients: [alex], context_id: "c1" },
      { channel: "notify.mobile_app_sam_phone", recipients: [sam], context_id: "c2" },
    ],
  };
  const records = [
    { ...base, ...family, id: "r11", time: at(0, 19, 58), source: "notify", channel: "notify.family", title: "Doorbell", message: "Someone is at the front door.", origin: automation("front_door_doorbell", "Front door: doorbell"), data: { data: { tag: "doorbell_ring", image: "/doorbell.svg" } } },
    { ...base, id: "r12", time: at(0, 18, 50), source: "notify", channel: "notify.mobile_app_alex_phone", title: "Driveway", message: "The camera recorded motion.", recipients: [alex], origin: automation("driveway_motion", "Driveway: motion"), data: { data: { tag: "driveway_motion", image: "/driveway.svg", video: "/driveway.mp4" } } },
    { ...base, ...family, id: "r1", time: at(0, 18, 42), source: "notify", channel: "notify.family", title: "Laundry", message: "The washing machine is done.", origin: automation("laundry_done", "Laundry: done"), data: { data: { tag: "laundry" } } },
    { ...base, id: "r2", time: at(0, 18, 30), source: "speech", channel: "tts.speak", title: null, message: "Dinner is ready.", recipients: [speaker("kitchen", "Kitchen speaker"), speaker("living_room", "Living room speaker")], origin: automation("dinner_announcement", "Kitchen: dinner announcement"), data: { language: "en-US" } },
    { ...base, id: "r3", time: at(0, 17, 55), source: "persistent_notification", channel: "persistent_notification", title: "New devices discovered", message: "We discovered new devices on your network. [Check it out](/config/integrations/dashboard).", recipients: [everyone], origin: system, trace_path: null, source_ref: "config_entry_discovery" },
    { ...base, id: "r4", time: at(0, 17, 10), source: "notify", channel: "notify.mobile_app_alex_phone", title: "Garage", message: "The garage door has been open for 15 minutes.", recipients: [alex], origin: automation("garage_open_too_long", "Garage: open too long"), data: { data: { actions: [{ action: "CLOSE_GARAGE", title: "Close" }, { action: "LEAVE_GARAGE", title: "Leave open" }] } }, answers: [{ action: "CLOSE_GARAGE", time: at(0, 17, 12), user_id: "user-alex", reply_text: null }] },
    { ...base, id: "r9", time: at(0, 9, 5), source: "notify", channel: "notify.mobile_app_sam_phone", title: "Battery low", message: "Hallway motion sensor: 12 %.", recipients: [sam], origin: integration("battery_watch", "Battery Watch"), trace_path: null },
    { ...base, id: "r5", time: at(0, 16, 5), source: "persistent_notification", channel: "persistent_notification", title: "Login attempt failed", message: "Login attempt or request with invalid authentication from 192.168.1.23.", recipients: [everyone], origin: system, trace_path: null, source_ref: "http-login", status: "dismissed", status_time: at(0, 16, 20), status_by: { kind: "user", entity_id: null, name: null, trace_key: null, run_id: null, user_id: "user-alex" } },
    { ...base, id: "r6", time: at(0, 12, 3), source: "notify", channel: "notify.mobile_app_alex_phone", title: "Front door", message: "Unlocked for the parcel service.", recipients: [alex], origin: { kind: "user", entity_id: null, name: null, trace_key: null, run_id: null, user_id: "user-sam" }, trace_path: null },
    { ...base, ...family, id: "r7", time: at(-1, 22, 30), source: "notify", channel: "notify.family", title: "Good night", message: "All windows are closed and the alarm is armed.", origin: { kind: "script", entity_id: "script.good_night", name: "Good night", trace_key: "script.good_night", run_id: "r7", user_id: null } },
    { ...base, id: "r8", time: at(-1, 7, 15), source: "notify", channel: "notify.mobile_app_sam_phone", title: "Weather", message: "Rain expected from 10:00 – close the skylight.", recipients: [sam], origin: automation("rain_warning", "Weather: rain warning") },
  ];
  window.MOCK = {
    records,
    facets: {
      channels: [{ id: "notify.mobile_app_alex_phone", name: "notify.mobile_app_alex_phone" }],
      groups: [{ id: "notify.family", name: "notify.family" }],
      origins: [...new Map(records.map((r) => {
        const id = r.origin.entity_id ?? (r.origin.integration ? `integration.${r.origin.integration}` : r.origin.kind);
        return [id, { id, name: r.origin.entity_id || r.origin.integration ? r.origin.name : null }];
      })).values()],
      people: [
        { id: "user-alex", name: "Alex", picture: alex.picture },
        { id: "user-sam", name: "Sam", picture: sam.picture },
      ],
    },
  };
  // A week of made-up statistics: the same origins, more of them, counted per hour.
  const statistics = () => {
    const monday = new Date(today.getTime() - ((today.getDay() + 6) % 7) * 86400000);
    const origins = [
      ["automation.laundry_done", "Laundry: done", [9, 20], 1.4, 0, 0],
      ["automation.rain_warning", "Weather: rain warning", [6, 23], 1.1, 0, 0],
      ["integration.battery_watch", "Battery Watch", [8, 9], 0.9, 0, 0],
      ["automation.garage_open_too_long", "Garage: open too long", [17, 23], 0.8, 0.8, 0.7],
      ["integration.server_watch", "Server Watch", [0, 24], 0.7, 0, 0],
      ["script.good_night", "Good night", [22, 23], 1, 0, 0],
      ["system", null, [2, 4], 0.3, 0, 0],
      ["user", null, [12, 19], 0.2, 0, 0],
    ];
    let seed = 7;
    const random = () => ((seed = (seed * 16807) % 2147483647) - 1) / 2147483646;
    const heatmap = Array.from({ length: 7 }, () => Array(24).fill(0));
    const result = origins.map(([key, name]) => ({ key, name, notifications: 0, previous: 0, with_buttons: 0, answered: 0, bursts: 0, night: 0 }));
    const buckets = Array.from({ length: 7 }, (_, day) => ({ start: new Date(monday.getTime() + day * 86400000).toISOString(), counts: {} }));
    const days = Math.min(7, Math.floor((Date.now() - monday.getTime()) / 86400000) + 1);
    for (let day = 0; day < days; day += 1) {
      origins.forEach(([key, , [from, until], rate, buttons, answered], index) => {
        let count = Math.round(rate * (1 + random() * 2.5));
        if (key === "integration.server_watch" && day % 3 === 1) count += 6;
        const entry = result[index];
        for (let n = 0; n < count; n += 1) {
          const hour = (from + Math.floor(random() * (until - from))) % 24;
          heatmap[day][hour] += 1;
          if (hour >= 22 || hour < 7) entry.night += 1;
        }
        entry.notifications += count;
        entry.previous += Math.round(count * (0.6 + random() * 0.8));
        entry.with_buttons += Math.round(count * buttons);
        entry.answered += Math.round(count * answered);
        if (key === "integration.server_watch" && day % 3 === 1) entry.bursts += 1;
        if (count) buckets[day].counts[key] = count;
      });
    }
    const sum = (field) => result.reduce((total, entry) => total + entry[field], 0);
    return {
      period: "week",
      start: monday.toISOString(),
      end: new Date(monday.getTime() + 7 * 86400000).toISOString(),
      has_older: true,
      comparable: true,
      kept_since: new Date(today.getTime() - 90 * 86400000).toISOString(),
      totals: { notifications: sum("notifications"), with_buttons: sum("with_buttons"), answered: sum("answered"), bursts: sum("bursts"), night: sum("night"), previous: sum("previous") },
      buckets,
      heatmap,
      origins: result.sort((a, b) => b.notifications - a.notifications),
    };
  };
  window.MOCK.statistics = statistics;
  window.README_STATES = {
    "person.alex": { entity_id: "person.alex", state: "home", attributes: { user_id: "user-alex", friendly_name: "Alex", entity_picture: alex.picture } },
    "person.sam": { entity_id: "person.sam", state: "home", attributes: { user_id: "user-sam", friendly_name: "Sam", entity_picture: sam.picture } },
  };
})();
