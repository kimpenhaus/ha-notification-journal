// Made-up household for the README screenshots: Alex and Sam, no real data. render.mjs fixes the clock to a
// Saturday afternoon, so "today" here and the camera snapshots' timestamps fit together.
(() => {
  const avatar = (bg, fg) =>
    "data:image/svg+xml," +
    encodeURIComponent(
      `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'><rect width='40' height='40' fill='${bg}'/><circle cx='20' cy='16' r='7' fill='${fg}'/><ellipse cx='20' cy='36' rx='13' ry='10' fill='${fg}'/></svg>`,
    );
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const at = (dayOffset, h, m) => new Date(today.getTime() + dayOffset * 86400000 + (h * 60 + m) * 60000).toISOString();
  const alex = { kind: "person", id: "person.alex", name: "Alex", picture: avatar("#5e81ac", "#d8dee9"), user_id: "user-alex" };
  const sam = { kind: "person", id: "person.sam", name: "Sam", picture: avatar("#b48ead", "#eceff4"), user_id: "user-sam" };
  const automation = (id, name) => ({ kind: "automation", entity_id: `automation.${id}`, name, trace_key: `automation.${id}`, run_id: "r1", user_id: null });
  const system = { kind: "system", entity_id: null, name: null, trace_key: null, run_id: null, user_id: null };
  const everyone = { kind: "everyone", id: "persistent_notification", name: "Home Assistant", picture: null, user_id: null };
  const speaker = (id, name) => ({ kind: "speaker", id: `media_player.${id}`, name, picture: null, user_id: null });
  const base = { data: null, error: null, group: null, inner_calls: [], trace_path: "/config/automation/trace/x", source_ref: null, status_time: null, status_by: null, status: "sent", context_id: "c", answers: [] };
  const integration = (domain, name) => ({ kind: "integration", entity_id: null, name, integration: domain, trace_key: null, run_id: null, user_id: null });
  const byHand = (userId) => ({ kind: "user", entity_id: null, name: null, trace_key: null, run_id: null, user_id: userId });
  const family = {
    group: "notify.family",
    recipients: [alex, sam],
    inner_calls: [
      { channel: "notify.mobile_app_alex_phone", recipients: [alex], context_id: "c1" },
      { channel: "notify.mobile_app_sam_phone", recipients: [sam], context_id: "c2" },
    ],
  };
  const toAlex = { channel: "notify.mobile_app_alex_phone", recipients: [alex] };
  const toSam = { channel: "notify.mobile_app_sam_phone", recipients: [sam] };
  const garden = automation("camera_garden_animal", "Garden camera: animal");
  const street = automation("camera_street_vehicle", "Street camera: vehicle");
  const records = [
    {
      ...base, ...family, id: "r1", time: at(0, 16, 21), source: "notify", channel: "notify.family",
      title: "Visitor in the garden", message: "A fox is crossing the lawn.", origin: garden,
      data: { data: { tag: "garden_animal", image: "/garden-fox.jpg", actions: [{ action: "SPRINKLER_ON", title: "Sprinkler on" }, { action: "LET_IT_BE", title: "Let it be" }] } },
      answers: [{ action: "LET_IT_BE", time: at(0, 16, 23), user_id: "user-sam", reply_text: null }],
    },
    {
      ...base, ...toAlex, id: "r2", time: at(0, 13, 24), source: "notify",
      title: "Car outside", message: "A car stopped in front of the house.", origin: street,
      data: { data: { tag: "street_vehicle", image: "/street-car.jpg", video: "/street-car.mp4" } },
    },
    { ...base, ...family, id: "r3", time: at(0, 12, 58), source: "notify", channel: "notify.family", status: "partial", inner_calls: [family.inner_calls[0], { ...family.inner_calls[1], error: "Error sending notification to Sam's phone" }], title: "Laundry", message: "The washing machine is done – time to hang it up.", origin: automation("laundry_done", "Laundry: done"), data: { data: { tag: "laundry" } } },
    { ...base, id: "r4", time: at(0, 12, 30), source: "speech", channel: "tts.speak", title: null, message: "Lunch is ready!", recipients: [speaker("kitchen", "Kitchen speaker"), speaker("living_room", "Living room speaker")], origin: automation("lunch_announcement", "Kitchen: lunch is ready"), data: { language: "en-US" } },
    { ...base, ...toAlex, id: "r5", time: at(0, 11, 47), source: "notify", title: "Front door", message: "Unlocked for the parcel service.", origin: byHand("user-sam"), trace_path: null },
    { ...base, ...toAlex, id: "r6", time: at(0, 10, 15), source: "notify", title: "Garage", message: "The garage door has been open for 15 minutes.", origin: automation("garage_open_too_long", "Garage: open too long"), data: { data: { actions: [{ action: "CLOSE_GARAGE", title: "Close" }, { action: "LEAVE_GARAGE", title: "Leave open" }] } }, answers: [{ action: "CLOSE_GARAGE", time: at(0, 10, 16), user_id: "user-alex", reply_text: null }] },
    { ...base, ...toSam, id: "r7", time: at(0, 9, 5), source: "notify", title: "Battery low", message: "Hallway motion sensor: 12 %.", origin: integration("battery_watch", "Battery Watch"), trace_path: null },
    { ...base, ...toSam, id: "r8", time: at(0, 7, 30), source: "notify", status: "failed", error: "Error sending notification to Sam's phone", title: "Weather", message: "Rain from 11:00 – the skylight is still open.", origin: automation("rain_warning", "Weather: rain warning") },
    { ...base, id: "r9", time: at(0, 3, 12), source: "persistent_notification", channel: "persistent_notification", title: "Login attempt failed", message: "Login attempt or request with invalid authentication from 192.168.1.23.", recipients: [everyone], origin: system, trace_path: null, source_ref: "http-login", status: "dismissed", status_time: at(0, 8, 2), status_by: byHand("user-alex") },
    { ...base, ...family, id: "r10", time: at(-1, 22, 30), source: "notify", channel: "notify.family", title: "Good night", message: "All windows are closed and the alarm is armed.", origin: { kind: "script", entity_id: "script.good_night", name: "Good night", trace_key: "script.good_night", run_id: "r10", user_id: null } },
    { ...base, ...toAlex, id: "r11", time: at(-1, 18, 40), source: "notify", title: "Car outside", message: "A delivery van stopped in front of the house.", origin: street, data: { data: { tag: "street_vehicle" } } },
    { ...base, ...family, id: "r12", time: at(-1, 16, 5), source: "notify", channel: "notify.family", title: "Visitor in the garden", message: "A hedgehog is looking around the raised bed.", origin: garden, data: { data: { tag: "garden_animal", image: "/garden-hedgehog.jpg" } } },
    { ...base, id: "r13", time: at(-1, 14, 2), source: "persistent_notification", channel: "persistent_notification", title: "New devices discovered", message: "We discovered new devices on your network. [Check it out](/config/integrations/dashboard).", recipients: [everyone], origin: system, trace_path: null, source_ref: "config_entry_discovery" },
    { ...base, ...toSam, id: "r14", time: at(-1, 6, 48), source: "notify", title: "Visitor in the garden", message: "A cat is sitting on the terrace.", origin: garden, data: { data: { tag: "garden_animal" } } },
  ];
  window.MOCK = {
    records,
    facets: {
      channels: [
        { id: "notify.mobile_app_alex_phone", name: "notify.mobile_app_alex_phone" },
        { id: "notify.mobile_app_sam_phone", name: "notify.mobile_app_sam_phone" },
      ],
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
  // A week of made-up statistics up to today: the same origins, counted per hour, busier on the weekend.
  const statistics = () => {
    const monday = new Date(today.getTime() - ((today.getDay() + 6) % 7) * 86400000);
    // key, name, hours it happens in, per day on weekdays and on the weekend, share with buttons, share answered,
    // last week compared with this one
    const origins = [
      ["automation.camera_street_vehicle", "Street camera: vehicle", [7, 8, 8, 12, 13, 17, 17, 18, 19], 3, 2, 0, 0, 1.1],
      ["automation.camera_garden_animal", "Garden camera: animal", [5, 6, 6, 7, 16, 17, 20, 21, 22, 23], 2, 3.5, 1, 0.6, 0.65],
      ["automation.laundry_done", "Laundry: done", [10, 12, 13, 19, 20], 0.8, 2, 0, 0, 1],
      ["script.good_night", "Good night", [22, 23], 1, 1, 0, 0, 1],
      ["automation.garage_open_too_long", "Garage: open too long", [8, 10, 18, 19], 0.6, 1, 1, 0.8, 1.6],
      ["automation.rain_warning", "Weather: rain warning", [6, 7], 0.7, 0.5, 0, 0, 2.2],
      ["integration.battery_watch", "Battery Watch", [9], 0.3, 0.3, 0, 0, 1],
      ["integration.server_watch", "Server Watch", [1, 3, 11, 14], 0.3, 0.3, 0, 0, 0.5],
      ["system", null, [3, 14], 0.3, 0.3, 0, 0, 1],
      ["user", null, [11, 15], 0.3, 0.6, 0, 0, 1],
    ];
    let seed = 11;
    const random = () => ((seed = (seed * 16807) % 2147483647) - 1) / 2147483646;
    const heatmap = Array.from({ length: 7 }, () => Array(24).fill(0));
    const result = origins.map(([key, name]) => ({ key, name, notifications: 0, previous: 0, with_buttons: 0, answered: 0, bursts: 0, night: 0 }));
    const buckets = Array.from({ length: 7 }, (_, day) => ({ start: new Date(monday.getTime() + day * 86400000).toISOString(), counts: {} }));
    const now = new Date();
    const days = Math.min(7, Math.floor((now.getTime() - monday.getTime()) / 86400000) + 1);
    for (let day = 0; day < days; day += 1) {
      const weekend = day >= 5;
      origins.forEach(([key, , hours, weekday, weekendRate, buttons, answered, before], index) => {
        let count = Math.round((weekend ? weekendRate : weekday) * (0.5 + random()));
        const burst = key === "integration.server_watch" && day === 2;
        if (burst) count += 6;
        const entry = result[index];
        for (let n = 0; n < count; n += 1) {
          const hour = burst && n < 6 ? 3 : hours[Math.floor(random() * hours.length)];
          heatmap[day][hour] += 1;
          if (hour >= 22 || hour < 7) entry.night += 1;
        }
        entry.notifications += count;
        entry.previous += Math.round(count * before * (0.85 + random() * 0.3));
        entry.with_buttons += Math.round(count * buttons);
        entry.answered += Math.round(count * buttons * answered);
        if (burst) entry.bursts += 1;
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
