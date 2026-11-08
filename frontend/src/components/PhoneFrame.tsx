import type { ReactNode } from "react";

/** About 390x844, centered on the laptop screen (POC_MVP.md section 8). A7 styles it. */
export default function PhoneFrame({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto flex h-[844px] w-[390px] flex-col overflow-hidden rounded-[48px] border-[10px] border-gray-800 bg-white shadow-xl">
      <div className="flex-1 overflow-y-auto">{children}</div>
    </div>
  );
}
