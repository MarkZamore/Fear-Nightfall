import java.io.InputStreamReader;
import java.lang.instrument.Instrumentation;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Optional;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executor;
import java.util.concurrent.TimeUnit;
import java.util.zip.ZipFile;

/** Reads the staged book with FTB's parser and switches languages in the actual client. */
public final class QuestLocaleQa {
    private static final String MC = "net.minecraft.client.Minecraft";
    private static final String LANG = "assets/lanminecraft_fear_quests/lang/";

    public static void premain(String args, Instrumentation instrumentation) {
        Thread thread = new Thread(() -> run(instrumentation), "Fear Nightfall quest locale QA");
        thread.setDaemon(true);
        thread.start();
    }

    private static void run(Instrumentation instrumentation) {
        Path game = Path.of(System.getProperty("lanminecraft.steamqa.game"));
        Path output = Path.of(System.getProperty("lanminecraft.steamqa.evidence"));
        Object client = null;
        try {
            client = awaitClient(instrumentation);
            Object minecraft = client;
            ClassLoader loader = client.getClass().getClassLoader();
            Method snbt = loader.loadClass("dev.ftb.mods.ftblibrary.snbt.SNBT")
                .getMethod("tryRead", Path.class);
            Method parse = loader.loadClass("dev.ftb.mods.ftbquests.util.TextUtils")
                .getMethod("parseRawText", String.class);
            Method getString = loader.loadClass("net.minecraft.network.chat.Component").getMethod("getString");
            Class<?> gsonType = loader.loadClass("com.google.gson.Gson");
            Object gson = gsonType.getConstructor().newInstance();

            int snbtCount = 0;
            try (var paths = Files.walk(game.resolve("config/ftbquests/quests"))) {
                for (Path entry : paths.filter(p -> p.toString().endsWith(".snbt")).toList()) {
                    if (snbt.invoke(null, entry) == null) throw new IllegalStateException("Empty SNBT: " + entry);
                    snbtCount++;
                }
            }
            Path archive = game.resolve("config/paxi/resourcepacks/lanminecraft-fear-nightfall-quests.zip");
            try (ZipFile pack = new ZipFile(archive.toFile())) {
                Object languages = call(client, "m_91102_");
                for (String locale : new String[] {"en_us", "ru_ru", "en_us"}) {
                    Map<?, ?> expected;
                    try (var in = new InputStreamReader(pack.getInputStream(pack.getEntry(LANG + locale + ".json")),
                                                       StandardCharsets.UTF_8)) {
                        expected = (Map<?, ?>) gsonType.getMethod("fromJson", java.io.Reader.class, Class.class)
                            .invoke(gson, in, Map.class);
                    }
                    if (!locale.equals(call(languages, "m_264236_"))) {
                        CompletableFuture<?> reload = onClient(client, () -> {
                            languages.getClass().getMethod("m_264110_", String.class).invoke(languages, locale);
                            return (CompletableFuture<?>) call(minecraft, "m_91391_");
                        });
                        reload.get(300, TimeUnit.SECONDS);
                    }
                    if (!locale.equals(call(languages, "m_264236_"))) throw new IllegalStateException("Wrong language");
                    onClient(client, () -> {
                        for (Map.Entry<?, ?> entry : expected.entrySet()) {
                            String key = (String) entry.getKey();
                            String text = ((String) entry.getValue()).replace("%%", "%");
                            Object actual = parse.invoke(null, "{" + key + "}");
                            Object literal = parse.invoke(null, text);
                            if (!getString.invoke(literal).equals(getString.invoke(actual))
                                    || !styledText(literal, loader).equals(styledText(actual, loader))) {
                                throw new IllegalStateException("Translation/style mismatch: " + locale + " " + key);
                            }
                        }
                        return null;
                    });
                    Files.writeString(output.resolve("quests-locale.txt"),
                        locale + " entries=" + expected.size() + " snbtFiles=" + snbtCount + " PASS\n",
                        StandardCharsets.UTF_8, java.nio.file.StandardOpenOption.CREATE,
                        java.nio.file.StandardOpenOption.APPEND);
                }
            }
        } catch (Throwable failure) {
            try { Files.writeString(output.resolve("quests-locale-failure.txt"), failure.toString()); }
            catch (Exception ignored) {}
            failure.printStackTrace();
        } finally {
            Object minecraft = client;
            if (minecraft != null) ((Executor) minecraft).execute(() -> {
                try { call(minecraft, "m_91395_"); }
                catch (Exception failure) { failure.printStackTrace(); }
            });
        }
    }

    private record StyledText(Object style, String text) {}

    private static List<StyledText> styledText(Object component, ClassLoader loader) throws Exception {
        Class<?> formatted = loader.loadClass("net.minecraft.network.chat.FormattedText");
        Class<?> visitor = loader.loadClass("net.minecraft.network.chat.FormattedText$StyledContentConsumer");
        Class<?> style = loader.loadClass("net.minecraft.network.chat.Style");
        Method visit = Arrays.stream(formatted.getMethods())
            .filter(method -> Arrays.equals(method.getParameterTypes(), new Class<?>[] {visitor, style}))
            .findFirst().orElseThrow();
        List<StyledText> result = new ArrayList<>();
        Object collector = Proxy.newProxyInstance(loader, new Class<?>[] {visitor}, (proxy, method, args) -> {
            String text = (String) args[1];
            if (!text.isEmpty()) result.add(new StyledText(args[0], text));
            return Optional.empty();
        });
        visit.invoke(component, collector, style.getField("f_131099_").get(null));
        return result;
    }

    private static Object awaitClient(Instrumentation instrumentation) throws Exception {
        long deadline = System.nanoTime() + TimeUnit.MINUTES.toNanos(9);
        while (System.nanoTime() < deadline) {
            if (Thread.getAllStackTraces().values().stream().flatMap(Arrays::stream)
                .anyMatch(frame -> frame.getClassName().equals(MC) && frame.getMethodName().equals("m_91374_"))) {
                for (Class<?> c : instrumentation.getAllLoadedClasses()) {
                    if (!c.getName().equals(MC)) continue;
                    Object client = c.getMethod("m_91087_").invoke(null);
                    if (client != null && onClient(client, () -> call(client, "m_91265_") == null)) return client;
                }
            }
            Thread.sleep(500);
        }
        throw new IllegalStateException("Minecraft startup timed out");
    }

    private static Object call(Object target, String method) throws Exception {
        return target.getClass().getMethod(method).invoke(target);
    }

    private static <T> T onClient(Object client, Callable<T> action) throws Exception {
        CompletableFuture<T> done = new CompletableFuture<>();
        ((Executor) client).execute(() -> {
            try { done.complete(action.call()); }
            catch (Throwable failure) { done.completeExceptionally(failure); }
        });
        return done.get(120, TimeUnit.SECONDS);
    }
}
