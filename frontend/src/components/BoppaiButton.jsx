const base =
  "inline-flex items-center justify-center rounded-full font-['Nighty'] leading-[0.82] " +
  'transition-all duration-300 ease-[cubic-bezier(.34,1.56,.64,1)] focus:outline-none ' +
  'focus-visible:ring-4 focus-visible:ring-bp-geraldine/45 disabled:cursor-not-allowed disabled:opacity-50';

const variants = {
  filled:
    'bg-bp-flamingo text-bp-linen shadow-[0_1rem_2.5rem_rgba(97,55,17,0.2)] ' +
    'hover:-translate-y-2 hover:rotate-[-2deg] hover:scale-110 hover:shadow-[0_1.5rem_3.5rem_rgba(97,55,17,0.3)] ' +
    'active:translate-y-2 active:rotate-[5deg] active:scale-[0.78] active:shadow-[0_0.2rem_0.5rem_rgba(97,55,17,0.22)]',
  outline:
    'border-2 border-bp-flamingo bg-bp-linen text-bp-flamingo shadow-[0_0.6rem_1.6rem_rgba(97,55,17,0.08)] ' +
    'hover:-translate-y-1 hover:rotate-[-1deg] hover:scale-[1.04] hover:bg-bp-flamingo hover:text-bp-linen hover:shadow-[0_1rem_2.4rem_rgba(97,55,17,0.24)] ' +
    'active:translate-y-1 active:rotate-[3deg] active:scale-90 active:shadow-[0_0.2rem_0.5rem_rgba(97,55,17,0.18)]',
};

const sizes = {
  hero:
    'px-[clamp(1.6rem,2.7vw,3.2rem)] pb-[clamp(0.46rem,0.82vw,0.82rem)] ' +
    'pt-[clamp(0.66rem,1.05vw,1.05rem)] text-[clamp(3.2rem,5.8vw,7.2rem)]',
  card: 'px-6 pb-2.5 pt-3 text-4xl sm:text-[2.8rem]',
  small: 'px-5 pb-2 pt-2.5 text-3xl',
};

export default function BoppaiButton({
  as: Component = 'button',
  variant = 'filled',
  size = 'card',
  className = '',
  children,
  ...props
}) {
  return (
    <Component className={`${base} ${variants[variant]} ${sizes[size]} ${className}`} {...props}>
      {children}
    </Component>
  );
}
