import BuyModes from "@/components/BuyModes";

export const metadata = { title: "Buy | DealDesk" };

export default function BuyPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-text-primary">Buy from vendors</h1>
        <p className="mt-1 text-text-secondary">
          Choose how to start: chat or form. DealDesk sends the first message to your vendors, and then you play the vendors or let fake testers answer.
        </p>
      </div>
      <BuyModes />
    </div>
  );
}
