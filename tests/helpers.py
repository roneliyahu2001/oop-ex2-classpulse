from classpulse.app import ClassPulseApp, Config


class FakeClock:
    """Controllable time source so token expiry can be tested without sleeping."""

    def __init__(self, t: float = 1_700_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def make_app(clock=None, llm=None) -> ClassPulseApp:
    return ClassPulseApp(Config(db_path=":memory:", lecturer_pin="1234",
                                public_url="http://test", secret=b"k" * 32),
                         llm=llm, clock=clock or FakeClock())


HOMEWORK_A = ("Encapsulation hides the internal state of an object and exposes behaviour through methods. "
              "Inheritance lets a subclass reuse code, and polymorphism lets us call the same method on "
              "different classes. The strategy pattern is a good example of polymorphism in practice.")
HOMEWORK_B = ("Polymorphism means one interface with many implementations. Encapsulation protects data "
              "by keeping fields private. Inheritance creates an is-a relationship between classes, "
              "although composition is often preferred because it reduces coupling.")
HOMEWORK_SHORT = "Classes have objects and methods and also some fields inside them okay."
