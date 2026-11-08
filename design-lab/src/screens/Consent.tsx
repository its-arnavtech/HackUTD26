import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Eye, LockKeyhole, WalletCards } from "lucide-react";
import { ActionButton, Notice, PageTitle } from "../components";
export default function Consent() {
  const navigate = useNavigate();
  const [linked, setLinked] = useState(false);
  return (
    <div className="consent-screen screen-pad">
      <div className="consent-art" aria-hidden="true">
        <div className="orbit orbit-one" />
        <div className="orbit orbit-two" />
        <span className="paper-note">
          <WalletCards size={34} />
          <i />
          <i />
        </span>
        <span className="art-lock">
          <LockKeyhole size={25} />
        </span>
        <span className="art-star">✧</span>
      </div>
      <PageTitle
        eyebrow="A little certainty"
        description="Check the message against your real activity, so you don’t have to guess."
      >
        Let’s check
        <br />
        it together.
      </PageTitle>
      <div className="consent-points">
        <div>
          <Eye size={22} />
          <p>Read recent activity and bill status from your linked account.</p>
        </div>
        <div>
          <LockKeyhole size={22} />
          <p>
            Personal details are hidden before AI checks. Bank records stay in
            this session.
          </p>
        </div>
      </div>
      {linked ? (
        <>
          <Notice>Capital One linked for this demo.</Notice>
          <ActionButton onClick={() => navigate("/inbox")} arrow>
            Continue to messages
          </ActionButton>
        </>
      ) : (
        <ActionButton
          onClick={() => {
            setLinked(true);
            sessionStorage.setItem("sentinel-linked", "true");
          }}
          icon={<WalletCards size={21} />}
          arrow
        >
          Link Capital One
        </ActionButton>
      )}
      <button
        className="text-button"
        onClick={() => {
          sessionStorage.setItem("sentinel-linked", "false");
          navigate("/inbox?linked=false");
        }}
      >
        Continue without linking
      </button>
      <p className="quiet-note">
        You choose every action. We never move money.
      </p>
    </div>
  );
}
