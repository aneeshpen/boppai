import { ImageOff, Loader2, Minus, Plus, RefreshCw, ShoppingCart, Star, X } from 'lucide-react';
import PanelHeader from './PanelHeader';

// Pull the number out of a price string like "₹1,299.00" → 1299. Returns 0 when
// there's nothing numeric so a missing/odd price never breaks the running total.
function priceValue(price) {
  const match = String(price || '').replace(/,/g, '').match(/\d+(\.\d+)?/);
  return match ? Number(match[0]) : 0;
}

function formatINR(amount) {
  return `₹${Math.round(amount).toLocaleString('en-IN')}`;
}

// One found product: image, name, pack, rating, price, a pack-count stepper, and an X.
function ProductCard({ item, onSetCount, onRemove }) {
  const { ingredient, count = 1, product = {} } = item;

  return (
    <article className="group relative flex flex-col overflow-hidden rounded-xl border border-bp-jambalaya/10 bg-white shadow-sm shadow-bp-jambalaya/5 transition-colors duration-200 hover:border-bp-jambalaya hover:bg-bp-jambalaya hover:shadow-md hover:shadow-bp-jambalaya/20">
      <button
        type="button"
        onClick={() => onRemove?.(ingredient)}
        className="absolute right-1.5 top-1.5 z-10 grid h-6 w-6 place-items-center rounded-full border border-bp-jambalaya/12 bg-white/85 text-bp-domino shadow-sm transition hover:border-bp-flamingo/30 hover:bg-bp-flamingo hover:text-bp-linen"
        title={`Remove ${ingredient}`}
        aria-label={`Remove ${ingredient}`}
      >
        <X className="h-3.5 w-3.5" aria-hidden="true" />
      </button>

      <div className="grid aspect-square place-items-center overflow-hidden bg-bp-linen/60">
        {product.imageUrl ? (
          <img src={product.imageUrl} alt={product.name} className="h-full w-full object-cover" loading="lazy" />
        ) : (
          <ImageOff className="h-8 w-8 text-bp-jambalaya/20" aria-hidden="true" />
        )}
      </div>

      <div className="flex flex-1 flex-col gap-1.5 p-3">
        <div className="text-[10px] font-semibold uppercase tracking-wide text-bp-flamingo transition-colors duration-200 group-hover:text-bp-geraldine">
          {ingredient}
        </div>
        <h3 className="line-clamp-2 text-sm font-semibold leading-snug text-bp-jambalaya transition-colors duration-200 group-hover:text-bp-linen" title={product.name}>
          {product.name}
        </h3>

        <div className="flex items-center gap-2 text-xs text-bp-domino transition-colors duration-200 group-hover:text-bp-linen/70">
          {product.packSize && <span>{product.packSize}</span>}
          {product.rating && (
            <span className="inline-flex items-center gap-0.5 rounded bg-bp-conifer/30 px-1.5 py-0.5 font-semibold text-bp-jambalaya transition-colors duration-200 group-hover:bg-bp-conifer group-hover:text-bp-jambalaya">
              <Star className="h-3 w-3 fill-bp-jambalaya text-bp-jambalaya" aria-hidden="true" />
              {product.rating}
            </span>
          )}
        </div>

        <div className="mt-auto flex items-center justify-between gap-2 pt-1">
          <div className="text-sm font-semibold text-bp-jambalaya transition-colors duration-200 group-hover:text-bp-linen">
            {product.price || '—'}
            {count > 1 && <span className="ml-1 text-[11px] font-normal text-bp-domino group-hover:text-bp-linen/60">× {count}</span>}
          </div>

          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => onSetCount?.(ingredient, count - 1)}
              disabled={count <= 1}
              className="grid h-6 w-6 place-items-center rounded-md border border-bp-jambalaya/15 text-bp-domino transition-colors duration-200 hover:border-bp-flamingo/40 hover:bg-bp-flamingo/10 hover:text-bp-flamingo group-hover:border-bp-linen/25 group-hover:text-bp-linen/80 disabled:cursor-not-allowed disabled:opacity-40"
              title="Fewer packs"
              aria-label="Fewer packs"
            >
              <Minus className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
            <span className="min-w-5 text-center text-sm font-semibold text-bp-jambalaya transition-colors duration-200 group-hover:text-bp-linen">{count}</span>
            <button
              type="button"
              onClick={() => onSetCount?.(ingredient, count + 1)}
              className="grid h-6 w-6 place-items-center rounded-md border border-bp-jambalaya/15 text-bp-domino transition-colors duration-200 hover:border-bp-flamingo/40 hover:bg-bp-flamingo/10 hover:text-bp-flamingo group-hover:border-bp-linen/25 group-hover:text-bp-linen/80"
              title="More packs"
              aria-label="More packs"
            >
              <Plus className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>
    </article>
  );
}

// A plain, buttonless chip — used for the "still finding" and "couldn't find" groups.
function Tag({ label, pulse = false, muted = false }) {
  return (
    <span
      className={
        'inline-flex items-center rounded-full border px-4 py-1.5 text-sm font-medium '
        + (muted
          ? 'border-bp-jambalaya/10 bg-white/70 text-bp-domino'
          : 'border-bp-flamingo/20 bg-bp-flamingo/8 text-bp-flamingo')
        + (pulse ? ' animate-pulse' : '')
      }
    >
      {label}
    </span>
  );
}

// A chip with an action button that reveals on hover — the + on a pantry staple and
// the retry on a not-found item both use this. Shows a spinner while it's working.
function ActionTag({ label, icon: Icon, title, busy, disabled, onAction }) {
  return (
    <span className="group relative inline-flex items-center gap-1.5 rounded-full border border-bp-jambalaya/12 bg-white/80 py-1.5 pl-4 pr-1.5 text-sm font-medium text-bp-domino transition-colors duration-200 focus-within:border-bp-jambalaya hover:border-bp-jambalaya hover:bg-bp-jambalaya hover:text-bp-linen">
      {label}
      <button
        type="button"
        onClick={() => onAction?.(label)}
        disabled={disabled}
        className="grid h-6 w-6 place-items-center rounded-full bg-bp-flamingo/12 text-bp-flamingo transition-colors duration-200 group-hover:bg-bp-linen group-hover:text-bp-jambalaya disabled:cursor-not-allowed disabled:opacity-40"
        title={title}
        aria-label={title}
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Icon className="h-4 w-4" aria-hidden="true" />}
      </button>
    </span>
  );
}

// The Basket canvas. The Basket is everything in basket.json (found products, with the
// running total). The other groups are derived from the shopping list:
//   • processing  — Basket items not yet sourced (only while a fill is running)
//   • pantry      — long shelf-life staples we didn't auto-search; tap + to add one
//   • not found   — items the search couldn't fulfill (plain tags, no actions)
export default function BasketBoard({
  items = [],
  ingredientList = [],
  filling = false,
  sourcingItem = null,
  pushing = false,
  onSetCount,
  onRemove,
  onSourceItem,
  onBuyOnSwiggy,
}) {
  const found = items.filter((item) => item.status === 'found');
  const notFound = items.filter((item) => item.status === 'not_found');

  const resolved = new Set(items.map((item) => item.ingredient.toLowerCase()));
  const inBasket = (name) => resolved.has(String(name).toLowerCase());

  // Staples we deliberately didn't search, minus any already promoted into the Basket.
  const pantry = ingredientList.filter((it) => it?.name && it.category === 'pantry' && !inBasket(it.name));
  // Perishables still being sourced — only meaningful during a live fill.
  const processing = filling
    ? ingredientList.filter((it) => it?.name && (it.category || 'basket') !== 'pantry' && !inBasket(it.name))
    : [];

  const total = found.reduce((sum, item) => sum + priceValue(item.product?.price) * (item.count || 1), 0);
  const busy = filling || Boolean(sourcingItem) || pushing;
  const canBuy = found.some((item) => item.product?.productId);
  const isEmpty = !found.length && !notFound.length && !processing.length && !pantry.length;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg bg-bp-linen/40">
      <PanelHeader
        title="Basket"
        subtitle={`${found.length} item${found.length === 1 ? '' : 's'}${
          filling && processing.length ? ` · ${processing.length} finding…` : ''
        }`}
      >
        {filling && (
          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-bp-flamingo">
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            Filling your basket…
          </span>
        )}
        {total > 0 && (
          <div className="flex items-baseline gap-2 leading-none">
            <div className="text-2xl font-bold text-bp-jambalaya">Total</div>
            <div className="text-2xl font-bold text-bp-jambalaya">{formatINR(total)}</div>
          </div>
        )}
        {canBuy && (
          <button
            type="button"
            onClick={() => onBuyOnSwiggy?.()}
            disabled={busy}
            className="inline-flex items-center gap-2.5 rounded-full bg-bp-flamingo px-7 pb-1.5 pt-2 font-['Nighty'] text-3xl leading-none text-bp-linen shadow-[0_0.6rem_1.4rem_rgba(97,55,17,0.18)] transition-colors duration-200 hover:bg-bp-jambalaya focus:outline-none focus-visible:ring-4 focus-visible:ring-bp-geraldine/45 disabled:cursor-not-allowed disabled:opacity-50"
            title="Add your basket to your Swiggy Instamart cart"
          >
            {pushing ? (
              <>
                <Loader2 className="h-5 w-5 animate-spin" aria-hidden="true" />
                Sending to Swiggy…
              </>
            ) : (
              <>
                <ShoppingCart className="h-5 w-5" aria-hidden="true" />
                Buy on Swiggy
              </>
            )}
          </button>
        )}
      </PanelHeader>

      <main className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        {isEmpty ? (
          <div className="grid h-full place-items-center rounded-lg border border-dashed border-bp-jambalaya/15 bg-bp-linen/60 px-6 text-center text-sm text-bp-domino">
            No basket yet.
          </div>
        ) : (
          <>
            {found.length > 0 && (
              <div className="rounded-2xl border border-bp-conifer bg-bp-conifer/15 px-5 py-4">
                <div className="mb-3 flex items-baseline gap-2">
                  <span className="font-['Nighty'] text-2xl leading-none text-bp-jambalaya">In your basket</span>
                  <span className="text-sm text-bp-domino/70">— found on the grocery service</span>
                </div>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
                  {found.map((item) => (
                    <ProductCard key={item.ingredient} item={item} onSetCount={onSetCount} onRemove={onRemove} />
                  ))}
                </div>
              </div>
            )}

            {processing.length > 0 && (
              <div className="rounded-2xl border border-bp-flamingo/20 bg-bp-flamingo/8 px-5 py-4">
                <div className="mb-3 flex items-center gap-2 font-['Nighty'] text-2xl leading-none text-bp-flamingo">
                  <Loader2 className="h-5 w-5 animate-spin" aria-hidden="true" />
                  Finding on the grocery service
                </div>
                <div className="flex flex-wrap gap-2">
                  {processing.map((it) => (
                    <Tag key={it.name} label={it.name} pulse />
                  ))}
                </div>
              </div>
            )}

            {pantry.length > 0 && (
              <div className="rounded-2xl border border-bp-jambalaya/10 bg-white/70 px-5 py-4">
                <div className="mb-3 flex items-baseline gap-2">
                  <span className="font-['Nighty'] text-2xl leading-none text-bp-jambalaya">Pantry &amp; staples</span>
                  <span className="text-sm text-bp-domino/70">— you may already have these</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  {pantry.map((it) => (
                    <ActionTag
                      key={it.name}
                      label={it.name}
                      icon={Plus}
                      title={`Add ${it.name} to basket`}
                      busy={sourcingItem === it.name}
                      disabled={busy}
                      onAction={onSourceItem}
                    />
                  ))}
                </div>
              </div>
            )}

            {notFound.length > 0 && (
              <div className="rounded-2xl border border-bp-jambalaya/10 bg-white/70 px-5 py-4">
                <div className="mb-3 flex items-baseline gap-2">
                  <span className="font-['Nighty'] text-2xl leading-none text-bp-jambalaya">Couldn't find</span>
                  <span className="text-sm text-bp-domino/70">— tap to search again</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  {notFound.map((item) => (
                    <ActionTag
                      key={item.ingredient}
                      label={item.ingredient}
                      icon={RefreshCw}
                      title={`Search again for ${item.ingredient}`}
                      busy={sourcingItem === item.ingredient}
                      disabled={busy}
                      onAction={onSourceItem}
                    />
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
