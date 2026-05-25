import { useState } from "react";

interface Props {
  characterName: string;
}

export default function CharacterIllustration({ characterName }: Props) {
  const [imgError, setImgError] = useState(false);

  if (imgError) return null;

  return (
    <div className="character-illustration-container">
      <img
        src={`/api/characters/${encodeURIComponent(characterName)}/skin`}
        alt={characterName}
        onError={() => setImgError(true)}
        className="character-illustration-img"
      />
    </div>
  );
}
