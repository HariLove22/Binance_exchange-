import { Landing } from "./landing/Landing";
import { Login } from "./auth/Login";
import { Signup } from "./auth/Signup";
import { useHashRoute } from "./router";

function App() {
  const route = useHashRoute();

  if (route === "login") return <Login />;
  if (route === "signup") return <Signup />;
  return <Landing />;
}

export default App;
