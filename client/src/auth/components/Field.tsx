import { useState, type InputHTMLAttributes } from "react";

type FieldProps = InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  error?: string;
  hint?: string;
};

export function Field({ label, error, hint, id, type = "text", ...rest }: FieldProps) {
  const [show, setShow] = useState(false);
  const isPassword = type === "password";
  const inputType = isPassword && show ? "text" : type;

  return (
    <label className={`field ${error ? "field-error" : ""}`} htmlFor={id}>
      <span className="field-label">{label}</span>
      <span className="field-wrap">
        <input id={id} type={inputType} {...rest} />
        {isPassword && (
          <button
            type="button"
            className="field-toggle"
            onClick={() => setShow((s) => !s)}
            aria-label={show ? "Hide password" : "Show password"}
            tabIndex={-1}
          >
            {show ? "Hide" : "Show"}
          </button>
        )}
      </span>
      {error ? (
        <span className="field-msg err">{error}</span>
      ) : hint ? (
        <span className="field-msg">{hint}</span>
      ) : null}
    </label>
  );
}
