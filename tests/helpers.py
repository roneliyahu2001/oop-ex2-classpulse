from classica.app import ClassicaApp, Config

# A point on a campus, and two phones: one about 55 m away, one about 11 km away.
CLASSROOM = (32.1133, 34.8044)
NEAR = (32.1138, 34.8044)
FAR = (32.2133, 34.8044)


class FakeClock:
    """Controllable time source so token expiry can be tested without sleeping."""

    def __init__(self, t: float = 1_700_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


_apps: list[ClassicaApp] = []


def make_app(clock=None, llm=None, db: str = ":memory:") -> ClassicaApp:
    app = ClassicaApp(Config(db_path=db, lecturer_pin="1234", public_url="http://test",
                               secret=b"k" * 32),
                        llm=llm, clock=clock or FakeClock())
    _apps.append(app)
    return app


def close_apps() -> None:
    """Closes the databases of all apps made so far (call from tearDownModule)."""
    while _apps:
        _apps.pop().repo.close()


HOMEWORK_A = ("Encapsulation hides the internal state of an object and exposes behaviour through methods. "
              "Inheritance lets a subclass reuse code, and polymorphism lets us call the same method on "
              "different classes. The strategy pattern is a good example of polymorphism in practice.")
HOMEWORK_B = ("Polymorphism means one interface with many implementations. Encapsulation protects data "
              "by keeping fields private. Inheritance creates an is-a relationship between classes, "
              "although composition is often preferred because it reduces coupling.")
HOMEWORK_SHORT = "Classes have objects and methods and also some fields inside them okay."
