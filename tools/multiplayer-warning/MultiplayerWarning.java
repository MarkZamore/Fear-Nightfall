package lanminecraft.fearnightfall;

import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.screens.TitleScreen;
import net.minecraftforge.api.distmarker.Dist;
import net.minecraftforge.client.event.ScreenEvent;
import net.minecraftforge.eventbus.api.SubscribeEvent;
import net.minecraftforge.fml.common.Mod;

@Mod(MultiplayerWarning.ID)
public final class MultiplayerWarning {
    public static final String ID = "fear_nightfall_multiplayer_warning";

    @Mod.EventBusSubscriber(modid = ID, value = Dist.CLIENT)
    public static final class ClientEvents {
        @SubscribeEvent
        public static void initializeTitle(ScreenEvent.Init.Pre event) {
            if (event.getScreen() instanceof TitleScreen) {
                Minecraft.m_91087_().f_91066_.f_92083_ = true;
            }
        }
    }
}
