import { ChevronLeft, ChevronRight, ExternalLink, Play } from 'lucide-react';
import { useMemo, useState } from 'react';

const URL_RE = /https?:\/\/[^\s<>"']+/gi;
const MARKDOWN_LINK_RE = /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/gi;
const YOUTUBE_ID_RE = /[a-zA-Z0-9_-]{11}/;

function cleanUrl(value) {
  return String(value || '').trim().replace(/[)\].,;!?*_]+$/g, '');
}

function firstValidVideoId(value) {
  const match = String(value || '').match(YOUTUBE_ID_RE);
  return match?.[0] || null;
}

function youtubeVideoId(value) {
  let url;
  try {
    url = new URL(cleanUrl(value));
  } catch {
    return null;
  }

  const host = url.hostname.replace(/^www\./, '').replace(/^m\./, '');
  if (host === 'youtu.be') return firstValidVideoId(url.pathname.split('/').filter(Boolean)[0]);

  const isYouTube = host === 'youtube.com' || host === 'youtube-nocookie.com';
  if (!isYouTube) return null;

  if (url.pathname === '/watch') return firstValidVideoId(url.searchParams.get('v'));

  const [kind, id] = url.pathname.split('/').filter(Boolean);
  if (['embed', 'shorts', 'live'].includes(kind)) return firstValidVideoId(id);

  return null;
}

function isUrlLike(value) {
  return /^https?:\/\//i.test(String(value || '').trim());
}

export function extractYouTubeVideos(text) {
  if (!text) return [];

  const videos = new Map();
  const add = (url, label = '') => {
    const videoId = youtubeVideoId(url);
    if (!videoId || videos.has(videoId)) return;
    videos.set(videoId, {
      videoId,
      url: cleanUrl(url),
      label: label && !isUrlLike(label) ? label.trim() : '',
    });
  };

  for (const match of text.matchAll(MARKDOWN_LINK_RE)) {
    add(match[2], match[1]);
  }

  for (const match of text.matchAll(URL_RE)) {
    add(match[0]);
  }

  return [...videos.values()];
}

export function normalizeYouTubeVideos(items) {
  if (!Array.isArray(items)) return [];

  const videos = new Map();
  for (const item of items) {
    const url = cleanUrl(item?.url);
    const videoId = youtubeVideoId(url);
    if (!videoId || videos.has(videoId)) continue;
    const label = String(item?.title || '').trim();
    videos.set(videoId, {
      videoId,
      url,
      label: label && !isUrlLike(label) ? label : '',
    });
  }
  return [...videos.values()];
}

function thumbnailUrl(videoId, quality = 'hqdefault') {
  return `https://i.ytimg.com/vi/${videoId}/${quality}.jpg`;
}

function embedUrl(videoId) {
  const params = new URLSearchParams({
    autoplay: '1',
    playsinline: '1',
    rel: '0',
  });
  return `https://www.youtube.com/embed/${videoId}?${params.toString()}`;
}

function fallbackThumbnail(e, videoId) {
  const img = e.currentTarget;
  if (img.dataset.fallback === 'mqdefault') {
    img.dataset.fallback = 'hidden';
    img.style.display = 'none';
    return;
  }

  img.dataset.fallback = 'mqdefault';
  img.src = thumbnailUrl(videoId, 'mqdefault');
}

export default function YouTubeGallery({ text, videos: structuredVideos }) {
  const videos = useMemo(() => {
    const combined = new Map();
    for (const video of normalizeYouTubeVideos(structuredVideos)) combined.set(video.videoId, video);
    for (const video of extractYouTubeVideos(text)) {
      if (!combined.has(video.videoId)) combined.set(video.videoId, video);
    }
    return [...combined.values()];
  }, [text, structuredVideos]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [playingVideoId, setPlayingVideoId] = useState(null);

  if (!videos.length) return null;

  const selected = videos[Math.min(selectedIndex, videos.length - 1)];
  const hasMany = videos.length > 1;
  const isPlaying = playingVideoId === selected.videoId;

  function select(delta) {
    setSelectedIndex((current) => (current + delta + videos.length) % videos.length);
    setPlayingVideoId(null);
  }

  return (
    <section className="mb-3 overflow-hidden rounded-lg bg-stone-50">
      <div className="relative aspect-video w-full overflow-hidden rounded-t-lg bg-stone-900">
        {isPlaying ? (
          <iframe
            className="h-full w-full"
            src={embedUrl(selected.videoId)}
            title={selected.label || 'YouTube video player'}
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; fullscreen"
            allowFullScreen
          />
        ) : (
          <button
            type="button"
            onClick={() => setPlayingVideoId(selected.videoId)}
            className="group relative block h-full w-full overflow-hidden text-left"
            title="Play video"
            aria-label={`Play ${selected.label || 'YouTube video'}`}
          >
            <img
              src={thumbnailUrl(selected.videoId)}
              alt=""
              className="h-full w-full object-cover transition duration-200 group-hover:scale-[1.02]"
              onError={(e) => fallbackThumbnail(e, selected.videoId)}
            />
            <span className="absolute inset-0 bg-gradient-to-t from-stone-950/55 via-stone-950/10 to-transparent" />
            <span className="absolute inset-0 grid place-items-center">
              <span className="grid h-14 w-14 place-items-center rounded-full bg-white/95 text-orange-600 shadow-lg shadow-stone-950/30 transition group-hover:scale-105">
                <Play className="ml-0.5 h-6 w-6 fill-current" aria-hidden="true" />
              </span>
            </span>
          </button>
        )}

        {hasMany && (
          <>
            <button
              type="button"
              onClick={() => select(-1)}
              className="absolute left-2 top-1/2 grid h-8 w-8 -translate-y-1/2 place-items-center rounded-full bg-white/90 text-stone-700 shadow transition hover:bg-white hover:text-orange-600"
              title="Previous video"
              aria-label="Previous video"
            >
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
            </button>
            <button
              type="button"
              onClick={() => select(1)}
              className="absolute right-2 top-1/2 grid h-8 w-8 -translate-y-1/2 place-items-center rounded-full bg-white/90 text-stone-700 shadow transition hover:bg-white hover:text-orange-600"
              title="Next video"
              aria-label="Next video"
            >
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </button>
          </>
        )}
      </div>

      <div className="flex items-center justify-between gap-3 rounded-b-lg bg-stone-50 px-3 py-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-stone-800">
            {selected.label || 'YouTube video'}
          </div>
          <div className="truncate text-xs text-stone-400">
            {hasMany ? `${selectedIndex + 1} / ${videos.length} · ` : ''}youtube.com
          </div>
        </div>
        <a
          href={selected.url}
          target="_blank"
          rel="noopener noreferrer"
          className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-white/80 text-stone-500 transition hover:bg-orange-50 hover:text-orange-600"
          title="Open on YouTube"
          aria-label="Open on YouTube"
        >
          <ExternalLink className="h-4 w-4" aria-hidden="true" />
        </a>
      </div>

    </section>
  );
}
