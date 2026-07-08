import ProcessTabs from "./components/ProcessTabs";
import asIsProcess from "../data/asIsProcess.json";

export default function Home() {
  return (
    <div className="w-full min-h-screen flex flex-col justify-start items-center gap-2 p-10">
      <h1 className="text-2xl font-bold">
        BPM ENGINE
      </h1>
      <hr className="w-[80%]" />

      <div className="w-full max-w-6xl flex flex-col gap-4 mt-4">
        <ProcessTabs asIsProcess={asIsProcess} />
      </div>
    </div>
  );
}
