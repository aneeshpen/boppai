import { ChevronDown, ChevronUp, RefreshCw, ShoppingBasket, X } from 'lucide-react';
import PanelHeader from './PanelHeader';

const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MEALS = [
  ['breakfast', 'Breakfast'],
  ['lunch', 'Lunch'],
  ['dinner', 'Dinner'],
];

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const MONTHS_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// "2026-06-13" → { y, mo, d }. Parsed from parts (not `new Date(iso)`) so nothing
// shifts a day across timezones. Returns null for missing/malformed input.
function parseIso(iso) {
  if (typeof iso !== 'string') return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso.trim());
  if (!m) return null;
  const [, y, mo, d] = m;
  const date = new Date(Number(y), Number(mo) - 1, Number(d));
  if (Number.isNaN(date.getTime())) return null;
  return { y: Number(y), mo: Number(mo), d: Number(d) };
}

// A meal's date as a compact chip label: "2 Aug".
function shortDate(iso) {
  const p = parseIso(iso);
  return p ? `${p.d} ${MONTHS_SHORT[p.mo - 1]}` : '';
}

// One clean human week range, collapsing whatever the two endpoints share so it
// never repeats itself. long → "August 2–8, 2026"; short → "Aug 2–8". Falls back
// to the week's own title if the ISO dates are missing.
function formatRange(week, { long = false } = {}) {
  const a = parseIso(week?.startDate);
  const b = parseIso(week?.endDate);
  const M = long ? MONTHS : MONTHS_SHORT;

  if (!a && !b) return week?.title || '';
  if (!a || !b) {
    const one = a || b;
    return long ? `${M[one.mo - 1]} ${one.d}, ${one.y}` : `${M[one.mo - 1]} ${one.d}`;
  }
  if (a.y === b.y && a.mo === b.mo) {
    return long ? `${M[a.mo - 1]} ${a.d}–${b.d}, ${a.y}` : `${M[a.mo - 1]} ${a.d}–${b.d}`;
  }
  if (a.y === b.y) {
    return long
      ? `${M[a.mo - 1]} ${a.d} – ${M[b.mo - 1]} ${b.d}, ${a.y}`
      : `${M[a.mo - 1]} ${a.d} – ${M[b.mo - 1]} ${b.d}`;
  }
  return `${M[a.mo - 1]} ${a.d}, ${a.y} – ${M[b.mo - 1]} ${b.d}, ${b.y}`;
}

function weekById(weeks, selectedWeekId) {
  return weeks.find((week) => week.id === selectedWeekId) || weeks[0] || null;
}

function weekIndexById(weeks, selectedWeekId) {
  const index = weeks.findIndex((week) => week.id === selectedWeekId);
  return index >= 0 ? index : 0;
}

function dayHasMeals(day) {
  return MEALS.some(([key]) => day?.[key]?.name);
}

function DayCard({ day, weekId, onClearDay, onOpenMeal }) {
  const planned = day && !day.disabled && dayHasMeals(day);
  const disabled = !day || day.disabled || !planned;
  const firstMeal = MEALS.find(([key]) => day?.[key]?.name)?.[0];
  const dateLabel = shortDate(day?.date);

  // How many slots each dish name fills today — >1 means one shared batch.
  const dishSlotCounts = {};
  MEALS.forEach(([key]) => {
    const mealName = day?.[key]?.name;
    if (mealName) dishSlotCounts[mealName] = (dishSlotCounts[mealName] || 0) + 1;
  });

  return (
    <section
      className={
        'relative flex min-h-48 flex-col rounded-xl border px-4 py-3 transition ' +
        (disabled
          ? 'border-bp-jambalaya/8 bg-bp-linen/50 text-bp-domino/60'
          : 'border-bp-jambalaya/10 bg-white text-bp-jambalaya shadow-sm shadow-bp-jambalaya/5')
      }
    >
      <div className="mb-3 flex min-h-8 items-center justify-between gap-2">
        {dateLabel ? (
          <span
            className={
              'shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold leading-none ' +
              (disabled ? 'bg-bp-jambalaya/5 text-bp-domino/55' : 'bg-bp-flamingo/12 text-bp-flamingo')
            }
          >
            {dateLabel}
          </span>
        ) : (
          <span aria-hidden="true" />
        )}

        <div className="flex min-w-0 items-center gap-2">
          {planned ? (
            <button
              type="button"
              onClick={() => onOpenMeal?.({ weekId, dayName: day.day, mealKey: firstMeal })}
              className="truncate rounded text-right text-sm font-semibold text-bp-jambalaya transition hover:text-bp-flamingo"
              title={`Open ${day.day}`}
            >
              {day?.day}
            </button>
          ) : (
            <h3 className="truncate text-sm font-semibold text-bp-domino/70">{day?.day}</h3>
          )}
          {planned && (
            <button
              type="button"
              onClick={() => onClearDay?.({ weekId, day: day.day })}
              className="grid h-7 w-7 shrink-0 place-items-center rounded-lg border border-bp-jambalaya/12 text-sm leading-none text-bp-domino transition hover:border-bp-flamingo/30 hover:bg-bp-flamingo/10 hover:text-bp-flamingo"
              title={`Clear ${day.day}`}
              aria-label={`Clear ${day.day}`}
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          )}
        </div>
      </div>

      {disabled ? (
        <div className="grid flex-1 place-items-center px-3 text-center text-xs text-bp-domino/50">
          No meal planned
        </div>
      ) : (
        <div className="-mx-1 divide-y divide-bp-jambalaya/8">
          {MEALS.map(([key, label]) => {
            const meal = day[key];
            // A dish name that fills more than one slot today is one cooked batch.
            const isBatch = meal?.name && dishSlotCounts[meal.name] > 1;
            const meta = [meal?.calories, meal?.servings > 1 ? `serves ${meal.servings}` : null]
              .filter(Boolean)
              .join(' · ');
            const content = (
              <>
                <div className="flex items-center gap-1.5">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-bp-flamingo transition-colors duration-200 group-hover:text-bp-geraldine">{label}</div>
                  {isBatch && (
                    <span className="rounded-full bg-bp-conifer/30 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-bp-jambalaya transition-colors duration-200 group-hover:bg-bp-conifer">
                      cooked once
                    </span>
                  )}
                </div>
                <div className="mt-1 flex items-start justify-between gap-3">
                  <div className="min-w-0 text-sm leading-snug text-bp-jambalaya transition-colors duration-200 group-hover:text-bp-linen">{meal?.name || 'No plan'}</div>
                  {meta && <div className="shrink-0 text-right text-xs leading-snug text-bp-domino transition-colors duration-200 group-hover:text-bp-linen/70">{meta}</div>}
                </div>
              </>
            );

            return meal?.name ? (
              <button
                key={key}
                type="button"
                onClick={() => onOpenMeal?.({ weekId, dayName: day.day, mealKey: key })}
                className="group block w-full rounded-md px-2 py-2 text-left transition-colors duration-200 hover:bg-bp-jambalaya"
                title={`View ${meal.name}`}
              >
                {content}
              </button>
            ) : (
              <div key={key} className="px-1 py-2">
                {content}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

function WeekSelector({ weeks, selectedWeekIndex, onWeekChange }) {
  const canGoUp = selectedWeekIndex > 0;
  const canGoDown = selectedWeekIndex < weeks.length - 1;
  // The current week plus a peek at its neighbours. Nulls (at the ends) are dropped
  // so there's no empty dead space — the cluster just centres itself.
  const slots = [selectedWeekIndex - 1, selectedWeekIndex, selectedWeekIndex + 1];

  const arrow =
    'grid h-9 w-9 place-items-center rounded-full border border-bp-jambalaya/15 bg-white/60 text-bp-jambalaya/70 ' +
    'transition hover:border-bp-flamingo/40 hover:bg-bp-flamingo/10 hover:text-bp-flamingo ' +
    'disabled:cursor-not-allowed disabled:border-bp-jambalaya/8 disabled:bg-transparent disabled:text-bp-jambalaya/20';

  return (
    <aside className="flex w-40 shrink-0 flex-col items-center justify-center gap-3 py-2">
      <button
        type="button"
        onClick={() => canGoUp && onWeekChange?.(weeks[selectedWeekIndex - 1].id)}
        disabled={!canGoUp}
        className={arrow}
        title="Previous week"
        aria-label="Previous week"
      >
        <ChevronUp className="h-4 w-4" aria-hidden="true" />
      </button>

      <div className="flex w-full flex-col gap-2">
        {slots.map((idx, slot) => {
          const week = weeks[idx];
          if (!week) return null;
          const active = slot === 1;

          return (
            <button
              key={week.id}
              type="button"
              onClick={() => onWeekChange?.(week.id)}
              className={
                'flex w-full flex-col justify-center rounded-xl border px-3 py-2.5 text-left transition ' +
                (active
                  ? 'border-bp-flamingo/30 bg-bp-flamingo/12 text-bp-jambalaya shadow-sm shadow-bp-flamingo/10'
                  : 'border-bp-jambalaya/10 bg-white/50 text-bp-domino hover:border-bp-flamingo/25 hover:bg-bp-flamingo/6 hover:text-bp-jambalaya')
              }
            >
              <span className="block text-xs font-semibold">Week {idx + 1}</span>
              <span className="mt-0.5 block truncate text-[10px] text-bp-domino/70">{formatRange(week)}</span>
            </button>
          );
        })}
      </div>

      <button
        type="button"
        onClick={() => canGoDown && onWeekChange?.(weeks[selectedWeekIndex + 1].id)}
        disabled={!canGoDown}
        className={arrow}
        title="Next week"
        aria-label="Next week"
      >
        <ChevronDown className="h-4 w-4" aria-hidden="true" />
      </button>
    </aside>
  );
}

export default function MealPlannerCalendar({
  weeks = [],
  selectedWeekId,
  onWeekChange,
  onClearDay,
  onOpenMeal,
  onBuildGroceryList,
  buildingList = false,
}) {
  const selectedWeekIndex = weekIndexById(weeks, selectedWeekId);
  const selectedWeek = weekById(weeks, selectedWeekId);
  const dayMap = new Map((selectedWeek?.days || []).map((day) => [day.day, day]));

  if (!weeks.length) {
    return (
      <div className="grid h-full place-items-center rounded-2xl border border-dashed border-bp-jambalaya/15 bg-bp-linen/60 px-6 text-center text-sm text-bp-domino">
        No meal planner yet.
      </div>
    );
  }

  const subtitle =
    weeks.length > 1
      ? `${formatRange(selectedWeek, { long: true })} · Week ${selectedWeekIndex + 1} of ${weeks.length}`
      : formatRange(selectedWeek, { long: true });

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <PanelHeader title="Meal Planner" subtitle={subtitle}>
        {onBuildGroceryList && (
          <button
            type="button"
            onClick={onBuildGroceryList}
            disabled={buildingList}
            className="inline-flex items-center gap-2.5 rounded-full bg-bp-flamingo px-7 pb-1.5 pt-2 font-['Nighty'] text-3xl leading-none text-bp-linen shadow-[0_0.6rem_1.4rem_rgba(97,55,17,0.18)] transition-colors duration-200 hover:bg-bp-jambalaya focus:outline-none focus-visible:ring-4 focus-visible:ring-bp-geraldine/45 disabled:cursor-not-allowed disabled:opacity-60"
            title="Consolidate the whole plan into one grocery list"
          >
            {buildingList ? (
              <>
                <RefreshCw className="h-5 w-5 animate-spin" aria-hidden="true" />
                Building grocery list…
              </>
            ) : (
              <>
                <ShoppingBasket className="h-5 w-5" aria-hidden="true" />
                Build grocery list
              </>
            )}
          </button>
        )}
      </PanelHeader>

      <div className="flex min-h-0 flex-1 gap-4 overflow-hidden p-1 pt-4">
        <WeekSelector
          weeks={weeks}
          selectedWeekIndex={selectedWeekIndex}
          onWeekChange={onWeekChange}
        />

        <main className="min-w-0 flex-1 overflow-y-auto pr-1">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {DAYS.map((dayName) => (
              <DayCard
                key={dayName}
                day={dayMap.get(dayName) || { day: dayName, disabled: true }}
                weekId={selectedWeek.id}
                onClearDay={onClearDay}
                onOpenMeal={onOpenMeal}
              />
            ))}
          </div>
        </main>
      </div>
    </div>
  );
}
