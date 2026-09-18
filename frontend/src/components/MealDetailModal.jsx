import { useEffect } from 'react';
import { ChevronLeft, ChevronRight, RefreshCw, X } from 'lucide-react';
import YouTubeGallery from './YouTubeGallery.jsx';

const MEAL_LABELS = { breakfast: 'Breakfast', lunch: 'Lunch', dinner: 'Dinner' };
const MACROS = [
  ['protein', 'Protein'],
  ['carbs', 'Carbs'],
  ['fat', 'Fat'],
  ['fiber', 'Fiber'],
];

const SECTION_HEADING = 'mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-bp-domino';

// A day's card, opened. Name + calories are known instantly; ingredients and
// macros arrive lazily, so those sections show a skeleton until they land. The
// chevrons loop through only the meals this day actually has.
export default function MealDetailModal({
  dayName,
  day,
  existingMeals,
  mealKey,
  onMealChange,
  loading,
  error,
  onRetry,
  onClose,
}) {
  const meal = day?.[mealKey];
  const index = existingMeals.indexOf(mealKey);
  const canCycle = existingMeals.length > 1;

  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape') onClose();
      else if (e.key === 'ArrowLeft' && canCycle) go(-1);
      else if (e.key === 'ArrowRight' && canCycle) go(1);
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index, existingMeals, canCycle]);

  if (!meal) return null;

  function go(delta) {
    const next = (index + delta + existingMeals.length) % existingMeals.length;
    onMealChange(existingMeals[next]);
  }

  // `ingredients` becomes an array once details are generated (empty is valid).
  const detailsReady = Array.isArray(meal.ingredients);
  const nutrition = meal.nutrition;
  const hasEmptyGeneratedDetails = detailsReady && meal.ingredients.length === 0 && !nutrition;

  // Slots this same dish fills today: >1 means one cooked batch.
  const sharedSlots = existingMeals.filter((key) => day[key]?.name === meal.name);
  const isBatch = sharedSlots.length > 1;
  const meta = [meal.calories, meal.servings > 1 ? `serves ${meal.servings}` : null]
    .filter(Boolean)
    .join(' · ');

  const navButton =
    'inline-flex items-center gap-1 rounded-full border border-bp-jambalaya/12 bg-white px-4 py-1.5 text-sm ' +
    'text-bp-domino transition hover:border-bp-flamingo/30 hover:bg-bp-flamingo/8 hover:text-bp-flamingo ' +
    'disabled:cursor-not-allowed disabled:opacity-40';

  return (
    <div
      className="fixed inset-0 z-40 grid place-items-center bg-bp-jambalaya/40 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="relative flex max-h-[85vh] w-full max-w-lg flex-col overflow-hidden rounded-2xl bg-white shadow-2xl shadow-bp-jambalaya/25"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-bp-jambalaya/10 bg-bp-linen/70 px-5 py-4">
          <div className="min-w-0">
            <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-bp-flamingo">
              {dayName} · {MEAL_LABELS[mealKey]}
            </div>
            <h2 className="mt-1 truncate font-['Nighty',_'DM_Sans',_sans-serif] text-[1.7rem] font-bold leading-[1] text-bp-jambalaya">{meal.name}</h2>
            {meta && <div className="mt-1 text-sm text-bp-domino">{meta}</div>}
            {isBatch && (
              <div className="mt-2 inline-flex items-center rounded-full bg-bp-conifer/30 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-bp-jambalaya">
                {sharedSlots.map((key) => MEAL_LABELS[key]).join(' + ')} · cooked once
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-bp-jambalaya/12 text-bp-domino transition hover:border-bp-flamingo/30 hover:bg-bp-flamingo/10 hover:text-bp-flamingo"
            title="Close"
            aria-label="Close"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {detailsReady && meal.youtubeVideos?.length > 0 && (
            <section className="mb-5">
              <h3 className={SECTION_HEADING}>Recipe videos</h3>
              <YouTubeGallery videos={meal.youtubeVideos} />
            </section>
          )}

          <section>
            <h3 className={SECTION_HEADING}>Nutrition</h3>
            {!detailsReady ? (
              <div className="grid grid-cols-4 gap-2">
                {MACROS.map(([key]) => (
                  <div key={key} className="h-14 animate-pulse rounded-xl bg-bp-jambalaya/8" />
                ))}
              </div>
            ) : nutrition ? (
              <div className="grid grid-cols-4 gap-2">
                {MACROS.map(([key, label]) => (
                  <div key={key} className="rounded-xl border border-bp-jambalaya/8 bg-bp-linen/60 px-2 py-2.5 text-center">
                    <div className="text-base font-bold text-bp-flamingo">{nutrition[key] || '—'}</div>
                    <div className="mt-0.5 text-[10px] font-semibold uppercase tracking-wide text-bp-domino">{label}</div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-bp-domino/60">No nutrition info.</p>
            )}
          </section>

          <section className="mt-5">
            <h3 className={SECTION_HEADING}>Ingredients</h3>
            {!detailsReady ? (
              error && !loading ? (
                <div className="rounded-xl border border-red-100 bg-red-50 px-3 py-3 text-sm text-red-600">
                  <p>Couldn't load ingredients.</p>
                  <button
                    type="button"
                    onClick={() => onRetry?.()}
                    className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-white px-2.5 py-1 text-xs font-medium text-red-600 transition hover:bg-red-100"
                  >
                    <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                    Retry
                  </button>
                </div>
              ) : (
                <div className="space-y-2">
                  {[0, 1, 2, 3].map((i) => (
                    <div key={i} className="flex items-center justify-between gap-4">
                      <div className="h-3 flex-1 animate-pulse rounded bg-bp-jambalaya/8" />
                      <div className="h-3 w-16 animate-pulse rounded bg-bp-jambalaya/8" />
                    </div>
                  ))}
                </div>
              )
            ) : hasEmptyGeneratedDetails ? (
              <div className="rounded-xl border border-red-100 bg-red-50 px-3 py-3 text-sm text-red-600">
                <p>Couldn't find usable details.</p>
                <button
                  type="button"
                  onClick={() => onRetry?.({ force: true })}
                  disabled={loading}
                  className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-white px-2.5 py-1 text-xs font-medium text-red-600 transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <RefreshCw className={'h-3.5 w-3.5 ' + (loading ? 'animate-spin' : '')} aria-hidden="true" />
                  Retry
                </button>
              </div>
            ) : meal.ingredients.length ? (
              <ul className="divide-y divide-bp-jambalaya/8">
                {meal.ingredients.map((ingredient, i) => (
                  <li key={i} className="flex items-center justify-between gap-4 py-2.5 text-sm">
                    <span className="text-bp-jambalaya">{ingredient.name}</span>
                    <span className="shrink-0 font-medium text-bp-domino">{ingredient.quantity}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-bp-domino/60">No ingredients listed.</p>
            )}
          </section>
        </div>

        <div className="flex items-center justify-between border-t border-bp-jambalaya/10 bg-bp-linen/40 px-5 py-3">
          <button
            type="button"
            onClick={() => go(-1)}
            disabled={!canCycle}
            className={navButton}
            aria-label="Previous meal"
          >
            <ChevronLeft className="h-4 w-4" aria-hidden="true" />
            Prev
          </button>

          <div className="flex gap-1.5">
            {existingMeals.map((key) => (
              <span
                key={key}
                className={
                  'h-2 w-2 rounded-full ' + (key === mealKey ? 'bg-bp-flamingo' : 'bg-bp-jambalaya/15')
                }
                aria-hidden="true"
              />
            ))}
          </div>

          <button
            type="button"
            onClick={() => go(1)}
            disabled={!canCycle}
            className={navButton}
            aria-label="Next meal"
          >
            Next
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      </div>
    </div>
  );
}
