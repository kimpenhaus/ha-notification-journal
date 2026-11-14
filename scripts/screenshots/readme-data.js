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
  const base = { data: null, error: null, group: null, inner_calls: [], trace_path: "/config/automation/trace/x", source_ref: null, status_time: null, status_by: null, status: "sent", context_id: "c" };
  const family = {
    group: "notify.family",
    recipients: [alex, sam],
    inner_calls: [
      { channel: "notify.mobile_app_alex_phone", recipients: [alex], context_id: "c1" },
      { channel: "notify.mobile_app_sam_phone", recipients: [sam], context_id: "c2" },
    ],
  };
  const records = [
    { ...base, ...family, id: "r1", time: at(0, 18, 42), source: "notify", channel: "notify.family", title: "Laundry", message: "The washing machine is done.", origin: automation("laundry_done", "Laundry: done"), data: { data: { tag: "laundry" } } },
    { ...base, id: "r2", time: at(0, 18, 30), source: "speech", channel: "tts.speak", title: null, message: "Dinner is ready.", recipients: [speaker("kitchen", "Kitchen speaker"), speaker("living_room", "Living room speaker")], origin: automation("dinner_announcement", "Kitchen: dinner announcement"), data: { language: "en-US" } },
    { ...base, id: "r3", time: at(0, 17, 55), source: "persistent_notification", channel: "persistent_notification", title: "New devices discovered", message: "We discovered new devices on your network. [Check it out](/config/integrations/dashboard).", recipients: [everyone], origin: system, trace_path: null, source_ref: "config_entry_discovery" },
    { ...base, id: "r4", time: at(0, 17, 10), source: "notify", channel: "notify.mobile_app_alex_phone", title: "Garage", message: "The garage door has been open for 15 minutes.", recipients: [alex], origin: automation("garage_open_too_long", "Garage: open too long") },
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
      origins: records.filter((r) => r.origin.entity_id).map((r) => ({ id: r.origin.entity_id, name: r.origin.name })),
      people: [
        { id: "user-alex", name: "Alex", picture: alex.picture },
        { id: "user-sam", name: "Sam", picture: sam.picture },
      ],
    },
  };
  window.README_STATES = {
    "person.alex": { entity_id: "person.alex", state: "home", attributes: { user_id: "user-alex", friendly_name: "Alex", entity_picture: alex.picture } },
    "person.sam": { entity_id: "person.sam", state: "home", attributes: { user_id: "user-sam", friendly_name: "Sam", entity_picture: sam.picture } },
  };
})();
