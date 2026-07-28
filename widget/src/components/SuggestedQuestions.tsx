interface Props {
  questions: string[];
  onSelect: (question: string) => void;
}

export function SuggestedQuestions({ questions, onSelect }: Props) {
  return (
    <div className="ask-ai-suggested">
      {questions.map((q, i) => (
        <button key={i} onClick={() => onSelect(q)}>
          {q}
        </button>
      ))}
    </div>
  );
}
