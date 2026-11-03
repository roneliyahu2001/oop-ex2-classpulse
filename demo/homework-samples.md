# Sample homework answers for the live demo
Paste each one from a different phone (or browser profile) in the Homework tab.
Question: "Explain the strategy and observer patterns with an example."

## Student A (good answer)
The strategy pattern defines a family of algorithms behind one interface so the algorithm can be swapped at runtime. For example, a payment module can use a CreditCardStrategy or a PayPalStrategy without changing the checkout code. The observer pattern lets objects subscribe to a subject and get notified on changes, like a newsletter where subscribers receive every new issue. In our project the event bus notifies student phones when a new poll opens.

## Student B (different, shorter)
Strategy is when you have an interface and several classes that implement it, and you choose one when the program runs, e.g. sorting with quicksort or mergesort. Observer is publish subscribe: a button notifies all its listeners when clicked.

## Student C (copied from A, for the copy-detection demo)
The strategy pattern defines a family of algorithms behind one interface so the algorithm can be swapped at runtime. For example, a payment module can use a CreditCardStrategy or a PayPalStrategy without changing the checkout code. The observer pattern lets objects subscribe to a subject and get notified on changes, like a newsletter. Thanks.
