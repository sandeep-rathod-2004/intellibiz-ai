import {useState, type FormEvent} from "react";
import {Link, Navigate, useLocation, useNavigate} from "react-router-dom";
import {BrainCircuit, LoaderCircle, ShieldCheck, Sparkles, TrendingUp, Activity, Database} from "lucide-react";
import {errorMessage} from "../lib/api";
import {useAuth} from "../lib/auth";

type AuthMode = "login" | "register";

export default function AuthPage({mode}: {mode: AuthMode}) {
  const isRegister = mode === "register";
  const {login, register, user, loading} = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const locationState = location.state as {notice?: unknown; noticeKind?: unknown} | null;
  const notice = typeof locationState?.notice === "string" ? locationState.notice : "";
  const noticeKind = locationState?.noticeKind === "error" ? "error" : "success";
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirmation, setPasswordConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (loading) return <div className="session-state" role="status">Verifying your session…</div>;
  if (user) return <Navigate to="/overview" replace />;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");

    if (isRegister) {
      if (password !== passwordConfirmation) {
        setError("Passwords do not match.");
        return;
      }
      if (new TextEncoder().encode(password).length > 72) {
        setError("Password must not exceed 72 UTF-8 bytes.");
        return;
      }
    }

    setBusy(true);
    try {
      if (isRegister) {
        const result = await register({
          email: email.trim(),
          full_name: fullName.trim(),
          password,
          password_confirmation: passwordConfirmation,
        });
        navigate("/login", {replace: true, state: {notice: result.message}});
        return;
      }

      await login(email.trim(), password);
      navigate("/overview", {replace: true, state: {notice: "Welcome to IntelliBiz AI."}});
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-shell">
      <div className="auth-orb orb-one" />
      <div className="auth-orb orb-two" />
      <section className="auth-card" aria-labelledby="auth-title">
        <div className="brand">
          <div className="brand-mark"><BrainCircuit size={23} /></div>
          <span>intellibiz<span className="mint">.</span></span>
        </div>
        <div className="eyebrow">INTELLIGENCE, IN MOTION</div>
        <h1 id="auth-title">
          {isRegister ? <>Create your<br /><em>workspace</em>.</> : <>Make every<br /><em>decision</em> count.</>}
        </h1>
        <p className="subtle">
          {isRegister
            ? "Create your private workspace to turn business data into confident action."
            : "Your business data, transformed into clarity, foresight and confident action."}
        </p>

        {notice && <div className={`notice auth-${noticeKind}`} role={noticeKind === "error" ? "alert" : "status"}>{notice}</div>}
        {error && <div className="notice auth-error" role="alert">{error}</div>}

        <form onSubmit={submit} className="auth-form">
          {isRegister && (
            <input
              autoComplete="name"
              maxLength={120}
              placeholder="Full name"
              value={fullName}
              onChange={event => setFullName(event.target.value)}
              required
            />
          )}
          <input
            autoComplete="email"
            type="email"
            placeholder="Work email"
            value={email}
            onChange={event => setEmail(event.target.value)}
            required
          />
          <input
            autoComplete={isRegister ? "new-password" : "current-password"}
            type="password"
            placeholder={isRegister ? "Password (10–72 UTF-8 bytes)" : "Password"}
            value={password}
            onChange={event => setPassword(event.target.value)}
            minLength={isRegister ? 10 : undefined}
            required
          />
          {isRegister && (
            <input
              autoComplete="new-password"
              type="password"
              placeholder="Confirm password"
              value={passwordConfirmation}
              onChange={event => setPasswordConfirmation(event.target.value)}
              minLength={10}
              required
            />
          )}
          <button className="primary-btn full" disabled={busy}>
            {busy && <LoaderCircle className="spin" size={16} />}
            {isRegister ? "Create account" : "Enter workspace"}
            <span>↗</span>
          </button>
        </form>

        <p className="auth-switch">
          {isRegister ? "Already have an account?" : "New to IntelliBiz?"}
          {" "}
          <Link to={isRegister ? "/login" : "/register"}>
            {isRegister ? "Sign in" : "Create an account"}
          </Link>
        </p>
        <div className="auth-foot"><ShieldCheck size={14} /> Private workspace · Secure access</div>
      </section>

      <div className="auth-visual" aria-hidden="true">
        <div className="visual-ring ring-a" />
        <div className="visual-ring ring-b" />
        <div className="visual-center"><Sparkles size={30} /></div>
        <div className="float-chip chip-a"><TrendingUp size={15} /> Predictive intelligence</div>
        <div className="float-chip chip-b"><Activity size={15} /> Live insights</div>
        <div className="float-chip chip-c"><Database size={15} /> Your data, understood</div>
      </div>
    </div>
  );
}
