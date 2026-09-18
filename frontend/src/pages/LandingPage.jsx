import { useNavigate } from 'react-router-dom';
import chefImage from '../assets/chef.png';
import MagneticMascot from '../components/MagneticMascot';

export default function LandingPage({ agents, savedAgentId }) {
  const navigate = useNavigate();

  function askBoppai() {
    const selectedAgent = agents.find((agent) => agent.id === savedAgentId && agent.installed && agent.loggedIn);
    navigate(selectedAgent ? '/' : '/select');
  }

  return (
    <main className="relative h-screen overflow-hidden bg-[radial-gradient(circle_at_50%_50%,#faa486_0%,#ef5927_46%,#613711_145%)] px-[clamp(1rem,4vw,4.75rem)] py-[clamp(1rem,3vh,2.5rem)] text-bp-linen">
      <section className="relative mx-auto flex h-full w-full max-w-[116rem] flex-col justify-center">
        <div className="relative z-10 grid min-h-0 flex-1 place-items-center">
          <div className="relative w-full">
            <p className="mb-[clamp(0.35rem,1vh,0.8rem)] font-['Nighty'] text-[clamp(2.2rem,4.8vw,4.8rem)] leading-[0.72] text-bp-jambalaya/85">
              Boppai
            </p>
            <h1 className="max-w-[14ch] font-['Nighty'] text-[clamp(5.2rem,14.5vw,17rem)] uppercase leading-[0.68] text-bp-linen drop-shadow-[0_0.18rem_0_rgba(97,55,17,0.28)] sm:max-w-none">
              <span className="block">From cravings</span>
              <span className="block">to cart.</span>
            </h1>
            <p className="mt-[clamp(0.8rem,1.6vh,1.5rem)] max-w-[33rem] font-['DM_Sans'] text-[clamp(1rem,1.7vw,1.35rem)] font-bold leading-[1.2] text-bp-linen/90">
              Tell Boppai what sounds good. He turns the hunger into a plan, a list, and the next grocery run.
            </p>
          </div>

          <MagneticMascot className="absolute bottom-[clamp(5.5rem,9vh,8rem)] right-[max(-2rem,-4vw)] z-20 w-[min(43vw,31rem)] min-w-[15rem] max-sm:bottom-[6.8rem] max-sm:right-[-3.6rem] max-sm:w-[17rem]">
            <img
              src={chefImage}
              alt=""
              className="block w-full rotate-[-3deg] drop-shadow-[0_2rem_2.8rem_rgba(97,55,17,0.34)]"
            />
          </MagneticMascot>
        </div>

        <div className="absolute bottom-[clamp(3.2rem,7vh,5.4rem)] left-[clamp(18rem,48vw,60rem)] z-30 max-sm:bottom-[1.25rem] max-sm:left-auto max-sm:right-[1rem]">
          <button
            type="button"
            onClick={askBoppai}
            className="inline-flex min-h-[4.25rem] min-w-[13.5rem] items-center justify-center rounded-full border-2 border-bp-linen bg-bp-linen px-8 pb-2 pt-3 font-['Nighty'] text-[clamp(2.75rem,4.8vw,4.8rem)] leading-[0.72] text-bp-flamingo shadow-[0_1rem_2rem_rgba(97,55,17,0.22)] transition-colors duration-200 hover:bg-bp-jambalaya hover:text-bp-linen focus:outline-none focus-visible:ring-4 focus-visible:ring-bp-geraldine/45"
          >
            Ask Boppai
          </button>
        </div>
      </section>
    </main>
  );
}
