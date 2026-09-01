/**
 * @startingPoint section="Components" subtitle="Text input with label, default/focus/disabled and a mono mode for IDs" viewport="700x110"
 */
export interface InputProps {
  label?: string;
  placeholder?: string;
  /** Use for code-like values — chunk IDs, hashes, file paths. */
  mono?: boolean;
  disabled?: boolean;
  defaultValue?: string;
  onChange?: (e: React.ChangeEvent<HTMLInputElement>) => void;
}

export function Input(props: InputProps): JSX.Element;
