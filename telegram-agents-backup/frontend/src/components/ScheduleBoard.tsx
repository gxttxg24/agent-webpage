import type { BotParticipant, ScheduleDay, ScheduleEvent } from "../types";

export function ScheduleBoard({
  days,
  loading,
  ownerProfile,
  participants,
  onOwnerChange,
  onRefresh
}: {
  days: ScheduleDay[];
  loading: boolean;
  ownerProfile: string;
  participants: BotParticipant[];
  onOwnerChange: (profile: string) => void;
  onRefresh: () => void;
}) {
  const hours = Array.from({ length: 15 }, (_, index) => 8 + index);
  const hasEvents = days.some((day) => day.events.length > 0);

  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Schedule</h2>
          <p className="text-sm text-slate-500">Next 7 days, shown for the selected participant.</p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={ownerProfile}
            onChange={(event) => onOwnerChange(event.target.value)}
            className="h-10 rounded-md border border-line bg-white px-3 text-sm text-slate-700 shadow-sm outline-none focus:border-brand"
          >
            {participants.map((participant) => (
              <option key={participant.profile} value={participant.profile}>
                {participant.display_name}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={onRefresh}
            className="rounded-md border border-line bg-white px-3 py-2 text-sm text-slate-700 shadow-sm hover:bg-slate-50"
          >
            Refresh
          </button>
        </div>
      </div>

      <div className="overflow-x-auto rounded-md border border-line bg-white shadow-soft">
        <div className="min-w-[860px]">
          <div className="grid grid-cols-[64px_repeat(7,minmax(112px,1fr))] border-b border-line bg-slate-50">
            <div className="border-r border-line px-2 py-3 text-xs font-medium text-slate-500">Time</div>
            {days.map((day) => (
              <div key={day.date} className="border-r border-line px-2 py-3 last:border-r-0">
                <div className="text-sm font-semibold">{day.weekday}</div>
                <div className="text-xs text-slate-500">{formatDateLabel(day.date)}</div>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-[64px_repeat(7,minmax(112px,1fr))]">
            <div className="border-r border-line bg-slate-50">
              {hours.map((hour) => (
                <div key={hour} className="h-16 border-b border-line px-2 py-1 text-xs text-slate-500">
                  {String(hour).padStart(2, "0")}:00
                </div>
              ))}
            </div>

            {days.map((day) => (
              <div key={day.date} className="relative border-r border-line last:border-r-0">
                {hours.map((hour) => (
                  <div key={hour} className="h-16 border-b border-line" />
                ))}
                {day.events.map((event) => (
                  <ScheduleEventBlock key={event.id} event={event} />
                ))}
              </div>
            ))}
          </div>

          {!loading && !hasEvents && (
            <div className="border-t border-line px-4 py-8 text-center text-sm text-slate-500">
              No events in this 7-day window.
            </div>
          )}
          {loading && (
            <div className="border-t border-line px-4 py-8 text-center text-sm text-slate-500">
              Loading schedule...
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ScheduleEventBlock({ event }: { event: ScheduleEvent }) {
  const start = minutesSinceDayStart(event.starts_at);
  const top = Math.max(0, (start - 8 * 60) / 60) * 64;
  const height = Math.max(42, (event.duration_minutes / 60) * 64);

  return (
    <div
      className="absolute left-1 right-1 overflow-hidden rounded-md border border-sky-200 bg-sky-50 px-2 py-1.5 text-xs leading-4 text-slate-800 shadow-sm"
      style={{ top, height }}
      title={`${event.start_time}-${event.end_time} ${event.title}`}
    >
      <div className="font-semibold">{event.title}</div>
      <div className="text-slate-500">{event.start_time}-{event.end_time}</div>
    </div>
  );
}

function formatDateLabel(value: string) {
  const [, month, day] = value.split("-");
  return `${month}/${day}`;
}

function minutesSinceDayStart(value: string) {
  const date = new Date(value);
  return date.getHours() * 60 + date.getMinutes();
}
